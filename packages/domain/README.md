# flowpilot-domain

FlowPilot 的纯 Python 领域值与不变量。本包不得导入 Web、Graph、ORM、Redis、MCP、
Policy 或 Provider SDK 框架。

## 生产依赖

| 依赖 | 用途 | 许可证 | 评估过的替代方案 | 攻击面与控制 |
|---|---|---|---|---|
| `rfc8785` | 计算契约定义的 RFC 8785 SHA-256 摘要 | Apache-2.0 | 未采用本地的不完整规范化器，因为审批与命令完整性要求完整实现 RFC 8785 | 仅处理受 Schema 约束的 JSON 值；调用方必须在构造领域对象前限制请求大小 |
