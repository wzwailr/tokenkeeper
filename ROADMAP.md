# tokenkeeper-ai Roadmap

## v0.2.x (当前) — 2026-06

- [ ] Azure 支持端到端验证
- [ ] 流式调用自动记账端到端验证
- [ ] SDK 错误路径端到端验证
- [x] py.typed + pre-commit
- [x] CONTRIBUTING / SECURITY / CoC
- [x] Dockerfile
- [ ] 结构化日志端到端验证
- [x] 包版本一致性
- [x] wheel 包含 Dashboard
- [x] 捕获范围矩阵

## v0.3.0 — 计划中

### LangChain Callback
```python
from tokenkeeper.integrations.langchain import TokenKeeperCallback

llm = ChatOpenAI(callbacks=[TokenKeeperCallback(project="my-app")])
```
- 目标支持 `on_llm_start` / `on_llm_end` 自动记账
- 目标覆盖 OpenAI / Anthropic / OpenAI-compatible 国产模型，完成状态以 `docs/CAPTURE_MATRIX.md` 为准

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
