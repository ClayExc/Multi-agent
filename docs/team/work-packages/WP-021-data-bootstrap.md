# WP-021：Data、Migration 与 Infra 基线

## 元数据

- 状态：BLOCKED
- 责任会话：S6-DATA
- 评审会话：S1-ARCH、S3-PLATFORM、S4-QUALITY
- 功能 ID：FP-SEC-002、FP-DATA-001、FP-DATA-003、FP-OPS-001
- 依赖工作包：S2/S3/S4/S5/S6 对同一 WP-000 `content_digest` 全部 ACCEPT、实现基线激活提交；公共 Python Workspace 依赖 WP-011
- 目标分支：`codex/s6/wp-021-data-bootstrap`

## 目标

- 建立 PostgreSQL Migration、RLS、Repository、Unit-of-Work、Inbox/Outbox 与执行账本骨架。
- 建立 Redis 可重建协调、故障恢复和事务一致性测试。
- 建立 PostgreSQL、Redis、Keycloak、OPA、OpenTelemetry 的开发 Compose 健康基线。

## 非目标

- LangGraph、领域状态、PolicyDecision 或 MCP 工具行为。
- 生产级高可用、灾备或破坏性数据迁移。
- 用 Redis、Queue 或 Trace 代替业务事实。
- 修改公共契约或自行增加跨进程字段。

## 允许修改路径

- `packages/persistence/**`
- `migrations/**`
- `infra/**`
- `tests/data/**`
- `.env.example`
- `.gitignore`
- 根级 Compose、Docker 与 CI 配置

本工作包是 M0 中环境变量、Compose 和部署依赖的唯一写入者；不得修改公共 Python Workspace。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | reviewed implementation baseline | S1-ARCH |
| Task/Command/Event、ToolRequest/Result、Audit/Security Event | v1 | S1-ARCH |
| Repository/Unit-of-Work Port | M0 internal | S5-CORE |
| 执行账本、幂等、回读 Port | M0 internal | S3-PLATFORM |
| Worker Lease/Checkpoint 需求 | M0 internal | S2-RUNTIME |
| Python Workspace | M0 | S5-CORE / WP-011 |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| Repository/Unit-of-Work Adapter | M0 | S5 |
| Checkpoint/Lease/Outbox Adapter | M0 | S2 |
| 执行账本、幂等、审计 Adapter | M0 | S3 |
| 双租户 RLS、故障与恢复 Fixture | M0 | S4 |
| 开发 Compose 与健康检查 | M0 | 全角色 |

## 架构与安全约束

- PostgreSQL 是业务事实源；Redis 只保存可重建协调状态。
- 表默认 RLS，至少两个租户；跨租户成功读写为 0。
- 唯一约束实现 Command/Tool 幂等，事务提交同时产生 Outbox。
- 写超时和未知结果保留对账状态，不能推断成功或盲重试。
- Migration 可重复且失败可诊断；生产凭据不得进入仓库。

## 实施内容

1. 建立 Persistence Port Adapter、SQLAlchemy 边界与初始迁移。
2. 建立双租户 RLS、Command Inbox、Task Projection、Outbox 和 Tool Ledger。
3. 建立 Redis 可重建协调、Worker Lease 与故障注入边界。
4. 建立开发 Compose、环境变量模板和健康检查。
5. 建立事务回滚、重复投递、序号缺口、Redis 丢失和恢复测试。
6. 通过 WP-011 公共命令接入测试，不并行修改 Makefile。

## 必须测试

- 正常：两个租户分别读写、事务提交、Outbox 产生和 Compose 健康。
- 边界：空批次、重复事件、序号缺口和过期 Lease。
- 失败：数据库/Redis/OPA 故障、事务回滚和 Migration 中断。
- 安全：跨租户、RLS 绕过、伪造 Tenant 和 Secret 泄漏被拒绝。
- 恢复/幂等：重复 Command/ToolRequest、Outbox 重投、Worker 重启和 Redis 清空。

## 验收命令

```bash
make test
make test-contract
make test-security
```

Compose 命令及空卷前置条件由本工作包在交接中给出。

## 完成定义

- 空卷 Compose 与 Migration 可重复运行。
- RLS、事务、Inbox/Outbox、幂等和恢复测试通过。
- 跨租户、重复逻辑写入和 Secret 泄漏均为 0。
- S1/S3/S4 完成跨角色审查。
