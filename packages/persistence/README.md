# FlowPilot 持久化层

`flowpilot-persistence` 实现以下 M0 数据边界：

- S5 的 `TaskRepositoryPort`、`TaskQueryPort`、`CommandInboxPort` 和
  `UnitOfWork`。
- S3 的执行账本与对账。
- S2 的 Checkpoint、Worker Lease、Fencing 和事务 Outbox。
- 可丢弃、并可根据 PostgreSQL 事实重建的 Redis 信号。

M7 产品组合通过 `compose_application_unit_of_work_factories` 将同一个
`DataUnitOfWorkFactory` 收窄为 S5 要求的 Command、Task Query 和 Task Event
三类工厂。每次调用都会创建独立事务；Task Event 的 Task 查询、Outbox 发布确认
和 Consumer Inbox 去重在同一租户绑定与同一提交中完成。适配器只把持久化层
`OutboxDelivery` 投影为 Application `OutboxEventView`，不会复制事件摘要、改变
PostgreSQL 事实或把 Redis 提升为事实源。

PostgreSQL 是唯一的业务事实源。每个租户事务通过 `flowpilot.tenant_id` 完成一次
绑定；Repository 会拒绝在同一事务内切换租户。迁移会在租户表上启用并强制执行
RLS。Redis 值只包含可重建的调度提示。

Persistence Port `flowpilot.persistence-ports.m0.v2` 显式存储
`checkpoint_sequence`。写入 Checkpoint 时传入 `expected_sequence`，在同一个
Unit-of-Work 事务中锁定并验证有效数据库租约、比较任务级序列，然后插入下一个
序列。`latest()` 必须接收租户、任务和线程标识，并且只按
`checkpoint_sequence` 排序。转换到 S2 `GraphState`/`LeaseToken` 的职责属于
Worker 装配层；本包绝不导入 `flowpilot_graph`。

`CoordinationRebuilder` 读取每个租户范围任务最新的持久化 Task Outbox 事件，恢复
并校验当前 Task v1 投影，而且只为 `RUNNABLE` 任务重建信号。已发布的 Outbox 行
仍是有效的重建输入，因此 Redis 数据丢失不会抹除调度来源。调用方必须提供可信
租户标识；请求中提供的租户标识不能作为重建范围。每个租户命名空间独立替换，
避免恢复过程删除其他租户的调度提示。

释放 Lease 时会撤销令牌但保留数据库行，使 `run_generation` 在正常 Handoff 和
租约过期接管时都保持单调递增。

PostgreSQL Adapter 依赖一个通过注入获得的精简异步连接协议。在 S5 接受
`DEPENDENCY_REQUEST.md` 中的驱动依赖请求之前，这能确保本包仍可导入；该协议
不会因此成为另一个事实源。后续驱动封装必须使用 Workspace 锁定的版本，并保持
此处已经测试的事务和租户绑定行为。

M0 有意不包含生产级高可用、破坏性迁移、跨区域恢复或通用 SQL 逃生通道。
