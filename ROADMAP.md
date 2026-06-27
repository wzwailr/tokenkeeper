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

## v0.3.0 — 第二阶段已完成的同进程捕获

### LangChain Callback
```python
from tokenkeeper.integrations.langchain import TokenKeeperCallback

llm = ChatOpenAI(callbacks=[TokenKeeperCallback(project="my-app")])
```
- 已验证 `on_llm_end` 自动记账和 `on_llm_error` 错误记录
- 已验证 OpenAI / Anthropic / OpenAI-compatible 国产模型的同进程捕获，完成状态以 `docs/CAPTURE_MATRIX.md` 为准

### Async 支持
- [x] `AsyncOpenAI` 自动拦截
- [x] `AsyncAnthropic` 自动拦截
- [x] OpenAI / Anthropic 流式 async 记账

## v0.4.0 — 第三阶段计划
- OpenAI-compatible proxy，用于非 Python、外部进程和不支持 monkey-patch 的 agent
- manual record 兜底路径增强
- 明确标注 provider 不返回 usage 时的零 token/零成本限制

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
