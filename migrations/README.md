# 数据库迁移

`0001_persistence_baseline.sql` 是 M0 基线。
`0002_checkpoint_sequence_cas.sql` 是它唯一的线性后继迁移，为 Checkpoint
存储增加任务级序列、确定性查询标识，以及原子比较并交换所需的数据库约束。
两个迁移都具备原子性和可重复执行性。PostgreSQL 角色设置为 `NOLOGIN`、
`NOSUPERUSER` 和 `NOBYPASSRLS`；部署时只能将这些角色授予仓库之外、已经完成
身份认证的工作负载登录角色。

本地使用空数据卷启动时，会将基线迁移挂载到 PostgreSQL 官方初始化目录。在后续
集成工作包接管迁移执行器之前，请使用下方命令显式应用 `0002`。`.down.sql` 文件
只用于开发环境重置，不会被自动挂载或执行。

手工验证：

```text
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0001_persistence_baseline.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0002_checkpoint_sequence_cas.sql
```

将两条命令各执行两次，以验证迁移可重复执行。每个文件都包含在
`BEGIN`/`COMMIT` 中，并使用 `ON_ERROR_STOP=1` 执行，因此任何语句失败都会回滚
整个迁移。

当多个任务共用同一个 `(tenant_id, thread_id)` 时，`0002` 的降级迁移会在修改
Schema 前失败，因为无法在不丢失数据的情况下恢复基线唯一性约束。开发环境成功
回滚后，必须先重新应用 `0002`，再运行当前持久化代码。
