# tokenkeeper-ai 架构文档

## 概述

tokenkeeper-ai 是一个低侵入的 AI API 成本监控库。当前阶段已验证打包、价格和本地账本基线；SDK monkey-patch、框架 callback、proxy 等捕获入口按阶段验证，真实完成范围见 `docs/CAPTURE_MATRIX.md`。

## 核心模块

```
tokenkeeper/
├── core.py              # GuardAPI 单例 — install/uninstall/record/set_budget
├── guard.py             # Guard 预算检查 — daily/monthly/per_call 限额
├── ledger.py            # Ledger SQLite 账本 — 读写 CallRecord
├── pricing.py           # 模型价格查找 — calculate_cost()
├── pricing_data.py      # 42 个内置模型价格表
├── cli.py               # 命令行入口 — tokenkeeper dashboard
├── alerting.py          # 告警 webhook — Slack/钉钉/飞书
├── logging_config.py    # 结构化日志 — JSON 格式
├── postgres_ledger.py   # PostgreSQL 后端
├── dashboard/
│   └── app.py           # Streamlit 看板
└── integrations/
    ├── openai_compat.py # OpenAI SDK monkey-patch
    ├── anthropic.py     # Anthropic SDK monkey-patch
    ├── langchain.py     # LangChain callback
    ├── hermes_connector.py  # Hermes state.db 同步
    └── hermes_http.py   # HTTP 层拦截（urllib monkey-patch）
```

## 数据流

```
用户代码                    tokenkeeper                    LLM API
─────────                  ───────────                    ──────
client.chat.completions    _wrap_create()
    .create() ──────────→    ├─ guard.check()
                             ├─ 原始 create() ──────────→ API
                             ├─ 提取 usage ←──────────── 响应
                             ├─ calculate_cost()
                             └─ ledger.record()
```

## Monkey-Patch 机制

tokenkeeper 劫持两个 SDK：

| SDK | 类 | 方法 |
|-----|-----|------|
| OpenAI | `resources.chat.completions.Completions` | `.create()` |
| OpenAI | `resources.chat.completions.AsyncCompletions` | `.create()` |
| Anthropic | `Anthropic().messages` | `.create()`（第二阶段修复并验证） |
| Anthropic | `AsyncAnthropic().messages` | `.create()`（第二阶段修复并验证） |

patch 策略：**fail-open**。patch 失败只记日志，原始调用不受影响。

## Hermes 集成

Hermes 桌面应用不走标准 SDK，API 调用从 Rust 侧发出。

**方案A（URLLIB 拦截）**：劫持 `urllib.request.OpenerDirector.open`，对所有 HTTP 请求进行模式匹配识别 LLM API。适用场景有限，须在该进程启动后才能生效，打包后的 app 无法使用。

**方案B（STATE.DB 同步）**：从 Hermes 的 `state.db` 读取 sessions 表 (`input_tokens`, `output_tokens`, `actual_cost_usd`)，增量同步到 tokenkeeper。兼容性好但非实时。

**当前**：前端使用 A，dashboard 再使用 B 补录历史数据。

## 客户端使用方式

### A. 简单引入
```python
guard.install(project="my-app")
guard.set_budget(daily_limit_usd=10.0, action="block")
```

### B. 手动记账
```python
guard.record(model="custom-llm", prompt_tokens=1000, completion_tokens=500, cost_usd=0.005)
```

### C. LangChain 集成
```python
llm = ChatOpenAI(callbacks=[TokenKeeperCallbackHandler(project="my-app")])
```

## 技术决策

1. **SQLite** 作为默认存储 — 零依赖，本地优先，数据不出机器
2. **fail-open** 策略 — 监控故障不影响业务，宁可漏记也不错调
3. **monkey-patch** 而非代理 — 对用户透明，不需要改 base_url
4. **pricing_data.py 独立文件** — 价格数据和逻辑分离，方便更新
5. **Streamlit** 而非自定义前端 — 快速迭代，数据可视化开箱即用
6. **guard 单例问题** — `from tokenkeeper import guard` 存在子模块遮蔽问题；内部统一使用 `from tokenkeeper.core import guard as api`
