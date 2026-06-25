# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI workflow
- Comprehensive .gitignore
- LICENSE (MIT) and CHANGELOG

## [0.1.0] - 2026-06-23

### Added
- 初始 MVP 发布
- OpenAI 兼容协议 SDK 自动拦截（monkey-patch）
- Anthropic 原生 SDK 自动拦截
- SQLite 账本（CallRecord + Ledger）
- 限额熔断（Guard + Budget）
- Streamlit 成本看板
- 价格表：42 个内置模型
  - OpenAI (10): gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, o1, o1-mini, o3, o3-mini, o4-mini
  - Anthropic (7): claude-3-5-sonnet, claude-3-5-haiku, claude-3-7-sonnet, claude-sonnet-4, claude-opus-4, claude-haiku-4
  - minimax (8): MiniMax-M3, M2.7, M2.7-highspeed, M2.5, M2.5-highspeed, M2.1, M2.1-highspeed, M2
  - DeepSeek (2): deepseek-chat, deepseek-reasoner
  - 阿里通义千问 (4): qwen-plus, qwen-turbo, qwen-max, qwen-long
  - 智谱 (3): glm-4-plus, glm-4-flash, glm-4-air
  - 百度文心 (3): ernie-4.0, ernie-3.5, ernie-speed
  - 月之暗面 (3): moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k
  - 零一万物 (2): yi-large, yi-medium
- 自定义价格注册（`register_custom_pricing()`）
- 环境变量覆盖（`TOKENKEEPER_PRICING_OVERRIDE`）
- 成本计算支持两种 cache 模式（OpenAI 子集 / Anthropic 独立）
- CSV / JSONL 导出
- CLI 命令：`tokenkeeper version/info/dashboard`
- pytest 测试：31 个全通过
- 真实 minimax M3 API 集成验证（minimax Anthropic 兼容 + minimax OpenAI 兼容）

### Known Limitations
- 流式响应：OpenAI 已支持并验证；Anthropic 代码已写但**未真实验证**（缺真实 Anthropic key）
- LangChain / LlamaIndex callback：未支持
- 多租户 / 团队管理：未支持
- 流式响应下的 tool_use / 多模态：未测试

[Unreleased]: https://github.com/wzwailr/tokenkeeper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wzwailr/tokenkeeper/releases/tag/v0.1.0
