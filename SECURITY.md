# Security Policy

## 报告漏洞

如果你发现安全漏洞，请 **不要** 提交公开 Issue。

发送邮件至项目维护者，或通过 GitHub Security Advisories 私密报告：
https://github.com/wzwailr/tokenkeeper/security/advisories/new

我们会在 48 小时内确认，并在修复后公开披露。

## 安全设计

tokenkeeper-ai 的安全原则：

- **数据不出机器** — 所有调用记录存在本地 SQLite，不上传任何服务器
- **核心记账不上传** — tokenkeeper core accounting 不上传调用记录。启用 webhook 告警、proxy 或外部同步功能时，tokenkeeper 会发起这些显式功能所需的网络请求。
- **最小权限** — monkey-patch 只修改 `create()` 方法签名，不读取、不修改你的 API key
- **fail-open** — patch 失败不影响原始 SDK 调用，只是不记账

## 依赖安全

定期运行：
```bash
pip-audit
```

## 支持的版本

| 版本 | 支持 |
|------|------|
| 0.2.x | ✅ 安全更新 |
| 0.1.x | ❌ 不再维护 |
