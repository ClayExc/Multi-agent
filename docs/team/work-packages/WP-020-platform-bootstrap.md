# WP-020：MCP Gateway、安全与策略基线

## 元数据

- 状态：BLOCKED_ON_WP021_LEDGER
- 责任会话：S3-PLATFORM
- 评审会话：S1-ARCH、S4-QUALITY、S6-DATA
- 功能 ID：FP-MCP-001、FP-MCP-002、FP-SEC-001、FP-SEC-004
- 依赖工作包：实现基线与 WP-011 H1 已合入；等待 WP-021 提供执行账本 Port
- 目标分支：`codex/s3/wp-020-platform-bootstrap`

## 目标

- 建立 MCP Gateway、Tool Registry、Policy、Security 与模拟 MCP 的最小安全骨架。
- 建立用户主体与 Agent 工作负载主体的确定性授权、审批和工具执行边界。
- 建立写动作幂等、回读校验、`UNKNOWN` 对账与凭据代理 Port。

## 非目标

- PostgreSQL Repository、Migration、RLS、Inbox/Outbox 或 Compose。
- 修改 LangGraph、领域状态和业务终态。
- 实现全部写工具、生产身份接入或真实企业凭据。
- 在公共契约外扩展跨进程对象。

## 允许修改路径

- `apps/mcp-gateway/**`
- `packages/tool-contracts/**`
- `packages/policy/**`
- `packages/security/**`
- `mcp-servers/**`
- `tests/platform/**`

不得修改 Persistence、Migration、Infra、公共 Python Workspace 或根级 Compose。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | reviewed implementation baseline | S1-ARCH |
| SecurityContextRef、PolicyDecision、PlannedAction、Approval、ToolRequest/Result | v1 | S1-ARCH |
| AuditEvent、SecurityEvent 与 ADR-0002/0004 | v1 | S1-ARCH |
| Python Workspace | M0 | S5-CORE / WP-011 |
| 执行账本、幂等、审计 Persistence Port | M0 internal | S6-DATA / WP-021 |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| MCP Gateway Inbound Port | M0 | S2 |
| Policy/Security Adapter Port | M0 internal | S2、S5 |
| 执行账本与回读持久化需求 | M0 internal | S6 |
| Audit/Security Event 与故障 Fixture | v1/M0 | S4、S6 |
| 模拟 MCP Tool Schema | M0 candidate | S2、S4 |

## 架构与安全约束

- Agent、API 和 Worker 不得绕过 MCP Gateway。
- 授权默认拒绝；PDP 或必须持久化的安全依赖不可用时写操作 fail-closed。
- 同时验证用户与 Agent 身份；Tenant 只能来自受信安全上下文。
- 审批绑定动作摘要、Tool Schema Hash、策略版本、主体、租户和过期时间。
- 写超时进入 `UNKNOWN`，先回读/对账，不能盲重试。
- 长期凭据不进入 Agent、日志、Trace 或持久化对象。

## 实施内容

1. 建立 Gateway 入口、Tool Registry、Schema 白名单与拒绝默认值。
2. 建立 SecurityContextRef 解析、PDP/PEP 和强类型 Obligation。
3. 建立单审批、动作摘要、策略版本与过期绑定。
4. 建立执行账本/幂等/回读 Persistence Port，并由 S6 提供实现。
5. 建立只读模拟 MCP 与固定 Schema。
6. 添加跨租户、策略不可用、审批重放、参数篡改和 `UNKNOWN` 测试。

## 必须测试

- 正常：授权、Gateway 调用、回读验证和安全事件。
- 边界：过期上下文、策略 Obligation、Schema Hash 变化。
- 失败：PDP/MCP/持久化 Port 不可用产生稳定错误。
- 安全：跨租户、错 Audience、角色伪造、审批重放、参数篡改和工具旁路被拒绝。
- 恢复：重复 ToolRequest、写超时 `UNKNOWN`、权威未执行证明和回读确认。

## 验收命令

```bash
make test
make test-contract
make test-security
```

若 WP-011/WP-021 尚未提供命令或 Adapter，必须记录真实依赖状态。

## 完成定义

- Gateway、策略、审批、安全、回读和恢复测试通过。
- 跨租户成功数、重复逻辑写入和 Secret 泄漏均为 0。
- 没有工具旁路、明文长期凭据或私有 Persistence 实现。
- S1/S4/S6 完成跨角色审查。
