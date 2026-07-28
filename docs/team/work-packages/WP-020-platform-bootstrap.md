# WP-020：Platform、安全与数据基线

## 元数据

- 状态：BLOCKED
- 责任会话：S3-PLATFORM
- 评审会话：S1-ARCH、S4-QUALITY
- 功能 ID：FP-MCP-001、FP-MCP-002、FP-SEC-001、FP-SEC-002、FP-SEC-004、FP-DATA-001、FP-DATA-003、FP-OPS-001
- 依赖工作包：S2/S3/S4 对同一 WP-000 `content_digest` 全部 ACCEPT、Git 基线提交
- 目标分支：`codex/s3-platform/wp-020-platform-bootstrap`

## 目标

- 建立 MCP Gateway、Policy、Security、Persistence 与模拟 MCP 的最小安全骨架。
- 建立 PostgreSQL 初始迁移、RLS 测试框架、Inbox/Outbox 数据模型边界。
- 建立 PostgreSQL、Redis、Keycloak、OPA、OpenTelemetry 的开发 Compose 健康基线。

## 非目标

- 实现全部写工具、审批闭环或生产级身份接入。
- 修改 LangGraph 状态和业务终态。
- 把 Redis 作为任务、审批或事件事实源。
- 在契约未冻结时自行扩展公共对象。

## 允许修改路径

- `apps/mcp-gateway/**`
- `packages/tool-contracts/**`
- `packages/policy/**`
- `packages/persistence/**`
- `packages/security/**`
- `mcp-servers/**`
- `migrations/**`
- `infra/**`
- `tests/platform/**`
- `.env.example`
- `.gitignore`
- 根级 Compose、Docker 与 CI 配置

本工作包是 M0 中环境变量、Compose 和部署依赖的唯一写入者；不得修改 `pyproject.toml`、`uv.lock` 或 `Makefile`。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | `1.0.0-rc.2` reviewed implementation baseline | S1-ARCH |
| SecurityContextRef / PolicyDecision | v1 | S1-ARCH |
| ToolRequest / ToolResult / PlannedAction / Approval | v1 | S1-ARCH |
| Task Command/Event 与 ADR-0003 | v1 | S1-ARCH |
| AuditEvent / SecurityEvent 与 ADR-0002 | v1 | S1-ARCH |
| Python workspace | WP-010 交付或兼容约束 | S2-RUNTIME |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| MCP Gateway Inbound Port | M0 skeleton | S2 |
| Policy/Persistence/Security Adapter Port | M0 internal | S2 |
| PostgreSQL Migration 与 RLS Fixture | M0 | S4 |
| 开发 Compose 与健康检查 | M0 | S4、S1 |
| 模拟 MCP Tool Schema | M0 candidate，变更走 RFC | S2、S4 |

## 架构与安全约束

- Agent、API 和 Worker 不得绕过 MCP Gateway 访问业务工具。
- 授权默认拒绝；PDP 不可用时写操作 fail-closed。
- `tenant_id` 来自受信安全上下文，不能由模型或工具参数覆盖。
- Inbox、Outbox 和任务投影使用 PostgreSQL；Redis 仅用于可重建协调。
- 表默认启用 RLS，测试至少使用两个租户。
- 审计不可采样；日志、Trace、事件不含明文 Token、密钥或真实 PII。

## 实施内容

1. 建立 Gateway 最小入口、Tool Registry 与拒绝默认值。
2. 建立 SecurityContextRef 解析端口和确定性 PolicyDecision 端口。
3. 建立 PostgreSQL 迁移、RLS、Command Inbox、Task Projection 和 Outbox 骨架。
4. 建立 Redis 可丢失协调适配器边界。
5. 建立只读模拟 MCP 的健康检查和固定 Schema。
6. 建立开发 Compose 与服务健康检查。
7. 添加跨租户、策略不可用、重复 Inbox 和 Outbox 重投测试框架。

## 必须测试

- 正常路径：两个租户各自写入/读取本租户测试数据；Compose 健康。
- 边界条件：过期安全上下文、空 Outbox 批次和重复消费。
- 失败路径：OPA、Redis、MCP 不可用产生稳定错误或降级结果。
- 安全负向：跨租户访问为 0；错 audience、角色伪造和绕 Gateway 被拒绝。
- 恢复/幂等：重复 Command 只入 Inbox 一次；Outbox 可重复投递且事件 ID 不变。

## 验收命令

```bash
make test
make test-contract
make test-security
# Compose 命令由本工作包在交接中给出
```

若 WP-010 尚未提供相应命令，必须记录为依赖阻塞，不能用手工检查冒充通过。

## 证据

- Migration/RLS 测试报告
- Compose 健康检查报告
- 契约与安全测试结果
- 按 `docs/team/HANDOFF_TEMPLATE.md` 创建的交接

## 完成定义

- 空卷 Compose 可启动并报告全部必需服务健康。
- 跨租户、默认拒绝、Inbox 去重和 Outbox 重投自动化测试通过。
- 没有工具旁路、明文凭据或比公共 Schema 更宽的对象。
- S1/S4 完成跨角色审查。
