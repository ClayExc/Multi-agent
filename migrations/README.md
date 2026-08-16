# 数据库迁移

`0001_persistence_baseline.sql` 是 M0 基线。
`0002_checkpoint_sequence_cas.sql` 是它的线性后继迁移，为 Checkpoint
存储增加任务级序列、确定性查询标识，以及原子比较并交换所需的数据库约束。
`0003_api_task_initialization.sql` 只向 `flowpilot_api`
授予 `tasks` 的 INSERT，用于 Command Tx-A 原子建立 Task v0；API 仍没有 UPDATE、
DELETE 或 TRUNCATE 权限。`0004_security_context_rls_binding.sql` 增加可撤销
SecurityContext 事实源、tenant/context/subject 事务绑定函数，并
纠正和复验既有运行时角色的 `NOLOGIN`、`NOSUPERUSER`、`NOINHERIT` 与
`NOBYPASSRLS`。`0005_governance_audit_query.sql` 增加可信
Governance QueryContext、签名游标所需的确定性查询索引、Policy Version 与
append-only Security Event 事实源、受 RLS 保护的闭合 Audit 投影视图。
`0006_knowledge_document_facts.sql` 是当前唯一线性 Head，增加知识文档、不可变版本、
可擦除正文、幂等 Inbox、元数据 Outbox 与索引任务事实源。六个迁移都
具备原子性和可重复执行性；部署时只能将运行时角色授予
仓库之外、已经完成身份认证的工作负载登录角色。

部署必须按 `0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006` 执行正向迁移。`.down.sql`
文件只用于开发环境重置，不会被自动执行。

手工验证：

```text
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0001_persistence_baseline.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0002_checkpoint_sequence_cas.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0003_api_task_initialization.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0004_security_context_rls_binding.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0005_governance_audit_query.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0006_knowledge_document_facts.sql
```

将这些命令各执行两次，以验证迁移可重复执行。每个文件都包含在
`BEGIN`/`COMMIT` 中，并使用 `ON_ERROR_STOP=1` 执行，因此任何语句失败都会回滚
整个迁移。

当多个任务共用同一个 `(tenant_id, thread_id)` 时，`0002` 的降级迁移会在修改
Schema 前失败，因为无法在不丢失数据的情况下恢复基线唯一性约束。开发环境回滚
必须严格按 `0006.down -> 0005.down -> 0004.down -> 0003.down -> 0002.down` 的逆序执行；
0006 存在任何知识事实、0005 存在任何 Governance 事实、0004 存在任何
SecurityContext 记录时均拒绝有损降级，
其余迁移也会在后继仍登记时先于任何 Schema 变化失败关闭。角色安全属性不会因降级
恢复为不安全状态。
