# SC-S3-PLATFORM-v1：MCP、安全、数据与基础设施

## 会话声明

```text
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=WP-020
FEATURE_IDS=FP-MCP-001,FP-MCP-002,FP-SEC-001,FP-SEC-002,FP-SEC-004,FP-DATA-001,FP-DATA-003,FP-OPS-001
WRITE_SCOPE=apps/mcp-gateway/**,packages/tool-contracts/**,packages/policy/**,packages/persistence/**,packages/security/**,mcp-servers/**,migrations/**,infra/**,tests/platform/**,WP-020授权共享文件
```

- 契约状态：REVIEW_ONLY
- 当前工作：[WP-020 Platform、安全与数据基线](../work-packages/WP-020-platform-bootstrap.md)
- 激活条件：S2/S3/S4 已对同一 rc2 `content_digest` 全部 `ACCEPT`，用户完成 Git 基线并为本会话建立独立 Worktree；发布级 `frozen` 不前置阻塞实现。

## 使命

构建 FlowPilot 的确定性强制执行边界，使错误或受攻击的模型无法绕过租户隔离、授权、审批、幂等、回读、凭据和审计控制。

## 决策权

S3 可以：

- 在冻结契约内设计 Gateway、PDP/PEP、Repository、迁移和 Infra 适配。
- 决定数据库约束、RLS、Outbox/Inbox、执行账本和对账实现。
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
| 输入 | 评审时为同一 rc2 `content_digest`、实现时为同一 frozen SecurityContextRef、PolicyDecision、PlannedAction、Approval、ToolRequest/Result、TaskEvent、AuditEvent、SecurityEvent、ADR-0002/0003/0004 |
| 输出给 S2 | 稳定 ToolResult、错误码、Policy Obligations 和平台 Port |
| 输出给 S4 | Audit/Security Event、故障注入接口、RLS/Outbox Fixture |
| 输出给 S1 | 威胁变化、契约安全缺口、RFC 和交接证据 |

## 工程约定

1. 所有业务工具只经 MCP Gateway；出站网络默认拒绝。
2. PDP/PEP 默认拒绝，写路径在依赖不可用时 fail-closed。
3. 同时验证用户与 Agent 身份；`tenant_id` 只能来自受信上下文。
4. 审批绑定动作摘要、Schema Hash、策略版本、主体、租户和过期时间。
5. `(tenant_id, tool, idempotency_key)` 与 Inbox 去重使用数据库唯一约束。
6. 写超时进入 `UNKNOWN`，先回读/对账，不能盲重试。
7. Token audience-bound、短时、最小 Scope，禁止透传用户 Token。
8. PostgreSQL 是事实源，表默认 RLS；Redis 只做可重建协调。
9. Audit 与 Security Event 不采样并分流，安全拒绝使用稳定原因码，不记录明文凭据和原始 PII。

## 必须交付的测试

- 正常：本租户授权、Gateway 调用、Outbox 提交与健康检查。
- 边界：过期上下文、空批次、策略 Obligation 和 Schema 版本变化。
- 失败：PDP/MCP/Redis/PostgreSQL 故障及稳定错误映射。
- 安全：跨租户、错 audience、角色伪造、审批重放、参数篡改和工具旁路。
- 恢复：Inbox 去重、Outbox 重投、写超时 `UNKNOWN` 与回读确认。

## 当前审查任务

在 `REVIEW_ONLY` 阶段只返回以下结论，不写仓库：

1. 针对 `flowpilot-m0-contracts-v1-rc2` 的精确 `content_digest`，确认 SecurityContextRef/PolicyDecision 的双主体、deny-overrides 和强类型 obligation 可 fail-closed 实现。
2. 确认 M0 单审批、PlannedAction/ToolRequest 绑定，以及 ToolResult 的 `UNKNOWN`/对账/重试语义可实现。
3. 确认 TaskEvent 生产者矩阵、AuditEvent 哈希链和独立 SecurityEvent 足以实现强制控制与证据分流。
4. 结论为 `ACCEPT`、`ACCEPT_WITH_RFC` 或 `REJECT`；非 `ACCEPT` 必须说明攻击面和迁移影响。

## 完成定义

- WP-020 的 Compose、契约、RLS、安全和恢复命令真实通过。
- 跨租户成功数为 0，重复逻辑写入为 0，Secret Scan 为 0。
- 没有工具旁路、明文长期凭据或 Redis 事实源。
- 交接由 S1/S4 复核后，相关功能才可进入下一状态。
