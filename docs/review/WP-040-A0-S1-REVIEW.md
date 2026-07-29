# WP-040-a0 S1 组合验收记录

> 2026-07-29 增补：S6 `WP-021-a2` 消费前置复核完成。后续链路改用
> [`CHAIN-WP040-A0-REMEDIATION-01`](../team/chain-authorizations/CHAIN-WP040-A0-REMEDIATION-01.md)
> 预授权执行。该授权只允许消费者续行，不改变本文的最终验收与合并门禁。

## 结论

- 日期：2026-07-29
- 评审角色：S1-ARCH
- 执行会话：S7-INTEGRATION
- Attempt：`WP-040-a0`
- 执行模式：`READ_ONLY_PARALLEL`
- 控制基线：`c6b7d2779c484bdf519a18399449fca35fc79e14`
- S7 基线：`55125ae3992311eab03cc888ea9c908486b4b727`
- 输入提交：
  - S2：`34bec05003cb59b3e16f1a16ae166b1f77465c46`
  - S5：`0be20f5b56d330f4da494ce4c3d46b183b09ae8b`
  - S6：`3e0101999061a44a3a5b2fd455ec792e3f73954e`
- ContractSet：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- S7 裁决：`NEEDS_REMEDIATION`
- S1 裁决：`ACCEPT_REVIEW_FINDINGS / BLOCK_COMPOSITION`

S7 的提交范围、路径所有权、依赖闭包和交接复算结论可接受。当前输入 Heads 不得进入主分支，也不激活 WP-040-a1；必须先关闭下列 P1 阻断。

## 已确认的阻断项

### S1-WP040-A0-001：TaskQuery Port 未闭合

S5 `TaskQueryPort.get(tenant_id, task_id)` 返回完整 `Task`，但 S6 的 Memory/PostgreSQL Task Repository 只有 `get_version()`。PostgreSQL Fixture 保存的 projection 也不是完整 Task v1，不能由 `Task.from_mapping()` 恢复。

责任角色：S6-DATA。

完成条件：

1. Memory/PostgreSQL Repository 实现租户隔离的完整 Task 查询。
2. 数据库存储并读取完整 Task v1 projection。
3. 畸形 projection、tenant/task 字段不一致和跨租户查询失败关闭。
4. S5 TaskQuery Protocol 类型门禁与 API→Persistence 黑盒通过。

### S1-WP040-A0-002：PlannedAction 摘要实现分叉

S5 已统一 `PlannedAction.digest()` 的可选 null 字段规范化；S6 `ExecutionIntent` 仍对原始 Mapping 调用 `canonical_sha256(planned_value)`。

责任角色：S6-DATA。

完成条件：

1. Ledger 只使用 `PlannedAction.from_mapping(...).digest()` 的领域权威实现。
2. 可选 null 字段省略/显式存在的契约等价输入具有一致回归证据。
3. S6 不复制第二套摘要规范。

### S1-WP040-A0-003：Checkpoint 持久化缺少原子序号 CAS

S2 `CheckpointPort.save()` 要求 `expected_sequence`，并在成功保存时把 `checkpoint_sequence` 加一。S6 `CheckpointPort.put()` 当前只验证 Lease/Fence 和 Checkpoint ID 不变性，没有在同一事务中比较当前序号。

薄适配器无法通过“先读后写”可靠补齐 CAS；并发或重复执行会产生竞态。

责任角色：S6-DATA。

完成条件：

1. `CheckpointRecord` 与 PostgreSQL Schema 显式保存 `checkpoint_sequence`。
2. `put(..., expected_sequence=...)` 在同一事务中验证活动 Fence、`run_generation` 和当前序号。
3. 首次写入只接受 expected `0`；后续只写入 `expected + 1`；过期 Fence 或旧序号稳定失败。
4. 相同 Checkpoint 的安全重放幂等，不同内容复用身份失败。
5. `latest()` 使用确定性序号排序，不依赖时间或随机 ID。

### S1-WP040-A0-004：Checkpoint 查询键与 Runtime 装配未闭合

S2 Graph Port 使用 `(tenant_id, task_id)` 加载状态；S6 `latest()` 当前只使用 `(tenant_id, thread_id)`。同一 Thread 下存在多个 Task 时可能读取错误 Task 的 Checkpoint。S2 Worker 也尚未提供 GraphState/LeaseToken 与 S6 CheckpointRecord/LeaseFence 的组合适配器。

责任角色：

- S6-DATA：提供按 tenant + task 严格隔离、同时保留 thread 关联的持久化查询原语。
- S2-RUNTIME：在 `apps/worker` 装配层实现类型转换、Task `thread_id` 解析、Clock/TTL 注入和稳定错误映射。

依赖方向：

- `packages/persistence` 不得依赖 `packages/graph`。
- 组合适配器位于 S2 的 Worker 装配层，可以依赖双方 Port。
- S2 的实现必须等待 S6 新持久化原语被 S1 接受。

完成条件：

1. tenant/task/thread 任一错配均失败关闭。
2. 旧 Worker fencing、Lease 过期、CAS 冲突和恢复路径具有组合测试。
3. S6 的原始错误不会直接泄漏为 API/Worker 外部错误。

### S1-WP040-A0-005：最终 Workspace 锁未形成

S5 root Workspace 已声明九个包及 LangGraph/SQLAlchemy/Psycopg/Redis，但当前锁文件只包含已存在的 API/Application/Domain 内部包；加入 S2/S6 源码后必须由 S5 刷新最终 `uv.lock`。

责任角色：S5-CORE。

完成条件：

1. 等待 S2/S6 新 Heads 稳定后刷新锁。
2. 九个包均进入安装闭包。
3. `uv lock --locked`、wheel、Core/Runtime/Data、类型检查和契约门禁通过。

## 调度裁决

本轮使用 `ORDERED`，不能把 S2/S6 修复当作可并行实现：

1. S6 `WP-021-a2`：关闭 001、002，并提供 003/004 所需的持久化原语。
2. S1 复核 S6 新 Head 与 Migration/实库证据，并建立预授权链路记录。
3. S2 `WP-010-a2`：消费 S6 原语实现 Worker 组合适配器，关闭 004 的
   消费侧；通过消费者门禁后直接交给 S5。
4. S5 `WP-011-a3`：在完整源码集合上刷新 Workspace 与 `uv.lock`，
   关闭 005；通过后直接交给 S7。
5. S7 `WP-040-a1`：从干净控制基线构造临时组合树，运行联合门禁。
6. S1 根据 WP-040-a1 证据决定主分支合入方式和顺序。

消息到达顺序不构成上述顺序；每一步必须由前一步的明确交接和授权
消费者结论解锁。正常路径不再逐步返回 S1。

## Advisory

- S2/S5/S6 输入分支路径交集为零，不代表运行时契约已经闭合。
- S2/S6 Dependency Request 状态应在新 Handoff 中与实际接收状态统一。
- 主 Worktree 当前存在 `.idea` 用户/IDE 变更；不属于本评审，但主分支集成前应由用户决定保留、提交或清理，S1 不代为修改。
- WP-040-a0 没有安装依赖或重跑完整测试，因此接受的是只读组合发现，不是实现验收。
