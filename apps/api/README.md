# flowpilot-api

这是 FlowPilot 的 FastAPI 适配器，负责存活探测、带版本的 `TaskCommand` 接入，以及
按租户隔离的只读 Task 投影查询。该进程只调用 Application 端口；不能修改 Task 状态、
创建权威事件、连接 Provider/MCP 端点，也不能持有上游凭据。

模块级 ASGI 应用有意保持未配置状态：健康检查始终可用；在组合根提供 Command Intake、
Task Query 和 Request Security 端口之前，命令与任务路由均以失败关闭方式拒绝请求。

## 运行时依赖

| 依赖 | 用途 | 许可证 | 评估过的替代方案 | 攻击面与控制 |
|---|---|---|---|---|
| `fastapi` | ASGI 路由、OpenAPI 生成、校验及错误钩子 | MIT | 仅使用 Starlette 路由需要重新实现 Schema 与依赖集成 | 处理 HTTP 解析和生成式 Schema；通过严格 Pydantic 模型与显式异常映射限制风险 |
| `pydantic` | 严格的 v1 请求/响应适配模型 | MIT | 手写字典校验容易造成 OpenAPI 漂移 | 解析不可信 JSON；所有嵌套模型禁止额外字段，并重新校验 Domain 不变量 |

`httpx` 是采用 BSD-3-Clause 许可证的开发依赖，仅用于进程内直接执行 ASGI 契约测试。

## 最小权限

- 调用已配置的 Application Command Intake 与 Task Query 端口。
- 从已配置的 Request Security 端口接收经过认证的身份。
- 不得直接访问数据库、队列、Provider、MCP、策略存储、Vault 或企业网络。
