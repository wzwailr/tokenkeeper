# Contributing to tokenkeeper-ai

感谢你愿意贡献！

## 快速开始

```bash
git clone https://github.com/wzwailr/tokenkeeper.git
cd tokenkeeper
pip install -e ".[all]"
pre-commit install
```

## 开发流程

1. **Fork** 仓库，从 `master` 创建 feature 分支
2. 写代码 + 测试（`pytest` 必须通过）
3. `pre-commit` 会自动运行 ruff + mypy
4. 提交 PR，描述改了什么、为什么

## 测试

```bash
pytest                          # 全部测试
pytest tests/test_basic.py      # 单文件
python scripts/validate_pricing.py  # 价格校验
```

## 代码风格

- Python 3.9+
- 类型注解（新函数必须有）
- ruff 格式化（pre-commit 自动处理）
- 文档字符串用 Google 风格

## 提交规范

```
feat: 新功能
fix: 修 bug
docs: 文档
test: 测试
chore: 杂项
release: 发版
```

## 问题反馈

GitHub Issues: https://github.com/wzwailr/tokenkeeper/issues
