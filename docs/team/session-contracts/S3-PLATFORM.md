# SC-S3-PLATFORM-v2：MCP、安全与策略执行

## 会话声明

```text
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=none
FEATURE_IDS=FP-SEC-001,FP-SEC-007
WRITE_SCOPE=apps/mcp-gateway/**,packages/tool-contracts/**,packages/policy/**,packages/security/**,mcp-servers/**,tests/platform/**,WP-020授权共享文件
```

- 契约状态：DEPENDENCY_WAIT
- 当前工作：M8 JWT/JWKS、ContextSource、工作负载与 Gateway 身份边界已验收。
- 激活条件：M9 的新 Work Package 与精确基线。

## 使命

构建 FlowPilot 的确定性工具强制执行边界，使错误或受攻击的模型无法绕过身份、授权、审批、工具白名单、幂等、回读和凭据控制。

## 决策权

S3 可以：

- 在冻结契约内设计 Gateway、PDP/PEP、Tool Registry、Security Adapter 和 MCP Server。
- 决定策略组合、工具执行账本 Port、回读对账协议和凭据代理细节。
- 下线未通过 Schema/策略审查的工具。
- 对不可实现或不安全的公共契约提交 RFC。

S3 不可以：

- 修改 LangGraph 业务路由、内部节点或任务终态。
- 修改公共契约、ADR 或验收状态。
- 让模型或 Agent 构造 SecurityContext、PolicyDecision 或长期凭据。
- 用 Prompt、Redis 锁或应用层查询代替 RLS/唯一约束等强制控制。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | 评审时为同一 rc2 `content_digest`；实现时为 SecurityContextRef、PolicyDecision、PlannedAction、Approval、ToolRequest/Result、S6 Persistence Port 与 ADR-0002/0003/0004 |
| 输出给 S2 | 稳定 ToolResult、错误码、Policy Obligations 和平台 Port |
| 输出给 S6 | 执行账本、幂等、回读、Audit/Security Event 的持久化需求与 Port |
| 输出给 S4 | Audit/Security Event、故障注入接口和安全 Fixture |
| 输出给 S1 | 威胁变化、契约安全缺口、RFC 和交接证据 |

## 工程约定

1. 所有业务工具只经 MCP Gateway；出站网络默认拒绝。
2. PDP/PEP 默认拒绝，写路径在依赖不可用时 fail-closed。
3. 同时验证用户与 Agent 身份；`tenant_id` 只能来自受信上下文。
4. 审批绑定动作摘要、Schema Hash、策略版本、主体、租户和过期时间。
5. `(tenant_id, tool, idempotency_key)` 的唯一性要求通过 S6 Persistence Port 强制，S3 不自行实现第二套存储。
6. 写超时进入 `UNKNOWN`，先回读/对账，不能盲重试。
7. Token audience-bound、短时、最小 Scope，禁止透传用户 Token。
8. Audit 与 Security Event 不采样并分流，安全拒绝使用稳定原因码，不记录明文凭据和原始 PII。
9. Gateway 每个阶段生成可关联、可重建的结构化执行信号；调试投影采用
   白名单字段，不能保存隐藏思维链或把 Trace 当成授权、账本与终态依据。

## 必须交付的测试

- 正常：本租户授权、Gateway 调用、回读验证与安全事件生成。
- 边界：过期上下文、空批次、策略 Obligation 和 Schema 版本变化。
- 失败：PDP/MCP/Redis/PostgreSQL 故障及稳定错误映射。
- 安全：跨租户、错 audience、角色伪造、审批重放、参数篡改和工具旁路。
- 恢复：重复 ToolRequest、写超时 `UNKNOWN` 与回读确认。

## 历史基线职责

按 `CHAIN-M1-PLATFORM-01` 执行 `WP-020-a1`：

1. 建立 MCP Gateway、Tool Registry、Schema 白名单和稳定拒绝码。
2. 建立双主体 SecurityContext 校验、Policy/PEP 与强类型 Obligation。
3. 建立 Approval、PlannedAction、PolicyDecision、ToolRequest 的完整绑定。
4. 通过 S6 Execution Ledger Port 实现幂等、`UNKNOWN`、回读与对账，不建立第二事实源。
5. 提供只读模拟 MCP、安全 Fixture，以及正常、边界、失败、安全和恢复测试。
6. 提供机器可读的执行时间线与脱敏调试投影，能关联请求、策略、审批、
   账本、MCP、回读、Audit 和 Security Event。
7. 完成后直接唤醒 S6 执行只读数据边界复核；正常路径不回传 S1。

## 完成定义

- WP-020 的 Gateway、策略、安全和工具恢复命令真实通过。
- 跨租户成功数为 0，重复逻辑写入为 0，Secret Scan 为 0。
- 没有工具旁路、明文长期凭据或 Redis 事实源。
- 交接由 S1/S4 复核后，相关功能才可进入下一状态。
