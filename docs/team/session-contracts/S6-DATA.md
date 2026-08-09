# SC-S6-DATA-v1：持久化、数据可靠性与基础设施

## 会话声明

```text
SESSION_ROLE=S6-DATA
WORK_PACKAGE=NONE
FEATURE_IDS=NONE
WRITE_SCOPE=packages/persistence/**,migrations/**,infra/**,tests/data/**,WP-021授权共享文件
```

- 契约状态：IDLE
- 当前工作：无；M7 数据组合、Task 初始化与迁移已进入主分支。
- 激活条件：后续 Agent Registry 分配 Base、Attempt、范围与退出条件。

## 使命

把 PostgreSQL 建成业务事实源，提供租户隔离、事务、Inbox/Outbox、执行账本、迁移、Redis 可重建协调和开发基础设施，使 S2/S3/S5 只依赖稳定 Persistence Port。

## 决策权

S6 可以：

- 设计 Repository、Unit-of-Work、事务边界、Migration、RLS 和数据库约束。
- 决定 Inbox/Outbox、执行账本、对账记录、游标和恢复实现。
- 维护 PostgreSQL/Redis/OPA/Keycloak/OTel 的开发 Compose 与健康检查。
- 对无法可靠落库或恢复的公共契约提交 RFC。

S6 不可以：

- 修改 LangGraph 路由、领域状态语义、PolicyDecision 或 MCP 工具行为。
- 用 Redis、队列或 Trace 替代 PostgreSQL 业务事实。
- 让数据库 Adapter 扩展比公共 Schema 更宽松的对象。
- 修改公共契约、ADR、验收状态或其他会话独占路径。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | Task/Command/Event、ToolRequest/Result、Audit/Security Event、ADR-0002/0003/0004、S3 执行账本需求、S5 Repository Port 与 WP-021 |
| 输出给 S2 | Checkpoint/Outbox/Worker Lease Adapter、稳定存储错误与恢复 Fixture |
| 输出给 S3 | 执行账本、幂等、回读证据和审计事件 Persistence Adapter |
| 输出给 S5 | Repository/Unit-of-Work 实现、Command Inbox 与 Task Projection Adapter |
| 输出给 S4 | 双租户 RLS、故障注入、Outbox 重投和恢复 Fixture |
| 输出给 S1 | 数据契约缺口、迁移风险、恢复证据与交接 |

## 工程约定

1. PostgreSQL 是 Task、审批、账本、Inbox/Outbox 和审计引用的事实源。
2. 表默认 RLS；Tenant 必须来自受信上下文，跨租户成功读取和写入为 0。
3. 唯一约束强制 Command/Tool 幂等，不以进程锁或 Redis 锁代替。
4. Task Projection、业务账本和 Outbox 在声明的本地事务边界内原子提交。
5. Redis 只保存可重建协调状态；删除 Redis 后业务事实和恢复能力保持。
6. Migration 前向可重复、失败可诊断；破坏性迁移必须独立工作包和审批。
7. `.env.example` 不含真实凭据；Compose 健康不等于业务验收通过。

## 必须交付的测试

- 正常：两个租户分别读写、Inbox/Outbox 提交、Compose 空卷启动。
- 边界：空 Outbox、重复事件、序号缺口和过期 Lease。
- 失败：PostgreSQL/Redis/OPA 故障、迁移中断和事务回滚。
- 安全：跨租户、RLS 绕过、伪造 Tenant、明文 Secret 和宽松数据库对象被拒绝。
- 恢复/幂等：重复 Command/ToolRequest、Outbox 重投、Worker 重启和 Redis 丢失。

## 历史基线职责

在 `REVIEW_ONLY` 阶段只读确认：

1. Task/Command/Event、ToolResult、Audit/Security Event 足以定义事务、唯一约束、RLS 和恢复。
2. `UNKNOWN`、权威回读、Outbox 至少一次及任务内序号语义可持久化且无盲重试。
3. S3 的安全执行与 S5 的应用用例可以只通过明确 Port 使用 S6。
4. 返回绑定当前 `content_digest` 的 `ACCEPT`、`ACCEPT_WITH_RFC` 或 `REJECT`。

## 完成定义

- WP-021 Compose、Migration、RLS、事务和恢复命令真实通过。
- 跨租户成功数、重复逻辑写入和 Secret 泄漏均为 0。
- Redis 丢失不损害业务事实，Outbox 可重投并可补洞。
- 交接由 S1/S3/S4 复核后，相关功能才可更新状态。
