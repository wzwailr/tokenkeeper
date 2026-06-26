# tokenkeeper-ai Roadmap

## v0.2.x (当前) — 2026-06

- [x] Azure 支持
- [x] 流式调用自动记账
- [x] 错误健壮化（重试+降级）
- [x] py.typed + pre-commit
- [x] CONTRIBUTING / SECURITY / CoC
- [x] Dockerfile
- [x] 结构化日志

## v0.3.0 — 计划中

### LangChain Callback
```python
from tokenkeeper.integrations.langchain import TokenKeeperCallback

llm = ChatOpenAI(callbacks=[TokenKeeperCallback(project="my-app")])
```
- 支持 `on_llm_start` / `on_llm_end` 自动记账
- 覆盖 OpenAI / Anthropic / 国产模型

### Async 支持
- `AsyncOpenAI` 自动拦截
- `AsyncAnthropic` 自动拦截
- 流式 async 记账

### 告警通知
- webhook（Slack / 钉钉 / 飞书）
- 邮件（SMTP）
- 预算阈值配置

### 看板增强
- PostgreSQL 后端（共享看板）
- 多项目切换
- 导出 PDF 报告

### 其他
- 内置价格更新 CI（每周自动 fetch）
- 多租户支持
- gRPC API（供其他服务查询账本）
