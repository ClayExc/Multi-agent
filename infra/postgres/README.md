# PostgreSQL 边界

- 业务事实存储在 `flowpilot` Schema 中。
- 租户表同时使用 `ENABLE ROW LEVEL SECURITY` 和
  `FORCE ROW LEVEL SECURITY`。
- Runtime 角色设置为 `NOLOGIN`、`NOSUPERUSER` 和 `NOBYPASSRLS`。
- 可信 Adapter 为事务设置唯一的本地 `flowpilot.tenant_id`，并拒绝租户切换。
- PlannedAction、PolicyDecision、Approval、Checkpoint 和 Audit 行只能追加，
  或只能进行受严格约束的状态变更。

Superuser/Migrator 访问不属于应用路径。紧急 Break-glass 访问必须使用独立登录、
短期授权，以及由后续运维工作包提供的审计流程。
