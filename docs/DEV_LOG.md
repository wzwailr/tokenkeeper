# 开发日志

记录 tokenkeeper-ai v0.2.0 → v0.3.0 开发过程中遇到的关键问题和解决方案。

## 2026-06-25: v0.2.0 发布

### 问题1: 看板断连 — DB 路径不一致
- **现象**: 看板永远显示 0 数据
- **原因**: 看板默认读 `./tokenkeeper.db`，用户 `guard.install(db_path=...)` 可能写在不同路径
- **尝试1** (失败): 只依赖环境变量 `TOKENKEEPER_DB`，无法清楚区分多个并发 dashboard 实例
- **尝试2** (失败): `guard.is_installed()` 检测 → dashboard 进程里 guard 未安装
- **最终方案**: CLI 通过 Streamlit 脚本参数 `-- --db <path>` 传递 DB，并同步设置 `TOKENKEEPER_DB`。已废弃全局临时文件 `%TEMP%/tokenkeeper_dashboard.json`，避免多个 dashboard 实例互相污染。

### 问题2: Streamlit 缓存旧 Ledger
- **现象**: `--db` 参数改了但数据不变
- **原因**: `@st.cache_resource` 不区分参数，缓存了第一个空 Ledger
- **解决**: `get_ledger(db_path)` 按路径缓存

### 问题3: Anthropic patch 报 NameError
- **现象**: `name '_wrap_anthropic_create' is not defined`
- **原因**: 函数名是 `_wrap_create`，调用处错写成 `_wrap_anthropic_create`
- **解决**: 统一为 `_wrap_create`

### 问题4: 全局变量名不一致
- **现象**: `name '_original_anthropic_create' is not defined`
- **原因**: `_original_create` vs `_original_anthropic_create` 混用
- **解决**: 统一为 `_original_anthropic_create`

## 2026-06-26: 生产级改造

### 问题5: `from tokenkeeper import guard` 返回模块而非单例
- **现象**: `guard.is_installed()` 报 AttributeError
- **原因**: Python import 优先级: 子模块 `guard.py` > 变量 `guard = GuardAPI()`
- **尝试1** (失败): `sys.modules["tokenkeeper.guard"]` 替换 → 破坏 `from tokenkeeper.guard import Budget`
- **最终方案**: 内部代码使用 `from tokenkeeper.core import guard as api`，公共 API 保持返回模块

### 问题6: 看板 `~` 路径未展开
- **现象**: `--db ~/.hermes/tokenkeeper.db` 找不到文件
- **原因**: `Path("~/.hermes/db")` 不自动展开 `~`，需要 `Path.expanduser()`
- **解决**: `_get_db_path()` 返回前调 `os.path.expanduser()`

### 问题7: cached_tokens > prompt_tokens 导致 ValueError
- **现象**: `ValueError: cached_tokens (120576) cannot exceed prompt_tokens (38135)`
- **原因**: 旧版 `CallRecord.__post_init__` 校验 `cached_tokens <= prompt_tokens`，但 Anthropic 的 cache_read 独立计费（不包含在 input_tokens 中）
- **解决**: 删除此校验（代码注释已说明 Anthropic 场景），`_row_to_record` 加 `except ValueError: pass`

### 问题8: Streamlit 加载旧 .pyc 模块
- **现象**: 源码已修复但看板仍崩溃
- **原因**: Python 的 `.pyc` 缓存先于代码修改加载
- **尝试1** (已废弃): CLI 启动时清 `__pycache__`
- **最终方案**: 不在运行时删除缓存目录；通过重启明确的 dashboard 进程和显式 DB 参数保证加载路径可验证。
- **教训**: 运行态必须显示实际 DB/进程入口，不能靠清缓存掩盖不确定性。

### 问题9: 终端输出污染源文件
- **现象**: bash 错误信息 `/usr/bin/bash: ... No such file or directory` 被写入 `.py` 文件末尾
- **原因**: 终端工具将 stderr 混入 stdout，某些情况下 stdout 被重定向到文件
- **临时方案**: 用 `write_file` + `execute_code` 代替 `terminal > file`；在写入后检查语法
- **状态**: 工具链问题，未根本解决

### 问题10: Hermes HTTP 拦截无效
- **假设**: Hermes 使用 Python 的 urllib/requests 发请求
- **实际**: Hermes 从 Rust 侧直接发 HTTP，绕过 Python 网络栈
- **当前方案**: 通过 `hermes_connector.py` 从 `state.db` 同步（非实时）

## 2026-06-27: 看板修复

### 问题11: load_calls 返回空数组
- **现象**: "最近调用"区域显示"该筛选条件下没有数据"，但 KPI 卡片有数据
- **原因**: `load_calls` 的 try/except 捕获了 `ledger.query()` 的 ValueError（旧 .pyc），返回 `[]`
- **解决**: 清除 `.pyc` 缓存 + 移除临时 try/except
