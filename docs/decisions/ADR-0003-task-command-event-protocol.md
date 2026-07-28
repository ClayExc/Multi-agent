# ADR-0003：Task、Command 与 Event 一致性协议

- 状态：Accepted
- 日期：2026-07-28

## 背景

FlowPilot 需要同时支持 API 并发写入、Worker 重试、LangGraph 恢复、Transactional Outbox 和 SSE 订阅。若 API 可以直接改 Task 状态，或把消息队列投递视为恰好一次，重复命令、过期写入和事件丢失会产生不可审计的状态分叉。

Task、LangGraph Checkpoint 和事件流承担不同职责：

- LangGraph Checkpoint 是跨业务节点的运行状态事实。
- Task 是面向 API、列表与治理查询的外部投影。
- Command 是请求改变任务的追加式意图。
- Event 是已提交事实的版本化通知，不是新的状态权威。

## 决策

1. API 只接受版本化 `TaskCommand`，不得直接设置图节点、审批结果或任务终态；API 不生产权威 `TaskEvent`。
2. 所有命令都携带由 API 在写入 Inbox 前预分配的不可猜测 `task_id`。创建命令的 `expected_task_version=null`；其他命令必须携带整数版本，版本不符返回稳定冲突错误。Task 业务事实仍由 Worker 提交，预分配 ID 不赋予 API 状态所有权。
3. 生产者生成不可猜测的 `command_id`；同一逻辑请求复用同一幂等键。`command_digest` 的唯一前像是包含 `command_type`、`tenant_id`、`task_id`、`actor`、`expected_task_version`、`payload` 的 JSON 对象，经 RFC 8785 规范化后计算 SHA-256；`command_id`、`idempotency_key`、`correlation_id`、`security_context`、`issued_at` 不进入摘要。
4. Command Inbox 的处理顺序固定为：
   1. 校验或重新计算 `command_digest`。
   2. 将 `tenant_id`、`actor.id/type` 分别与受信 `security_context` 的 `tenant_id`、`subject_id/type` 绑定；创建命令还绑定 `payload.purpose` 与 `security_context.purpose`。
   3. 查询 `(tenant_id, idempotency_key)`。
   4. 已存在且摘要相同时返回原处理结果，即使 Task Version 已前进。
   5. 已存在但摘要不同时返回稳定幂等冲突，并记录 SecurityEvent。
   6. 未存在时才校验 `expected_task_version`。
   7. 在同一事务内保留 `(tenant_id, task_id, expected_task_version)` 唯一槽位并写入 Inbox；同版本并发命令只有一个能获得槽位。
5. `command_id` 和 `(tenant_id, idempotency_key)` 都有唯一约束；键相同但 Payload 不同不能被当作成功重放。
6. Worker 只能通过 Application Port 驱动 LangGraph；Task 投影由确定性状态转换更新。按当前状态所有权，`task.created` 也由 Worker 在提交创建事实时产生。
7. Task 投影、业务账本和 Outbox Event 在各自声明的本地事务边界中原子提交；禁止数据库提交后再临时拼装事件。
8. `TaskEvent` 至少一次投递。消费者按 `event_id` 去重，不假设网络层恰好一次。
9. 同一 Task 的事件分配严格递增 `sequence`；多个事件可以共享同一 `task_version`，因为一个已提交的状态转换可产生多个事实。`task_version` 只在 Task 投影变化时递增。
10. 消费者发现 `sequence` 缺口时停止推断中间状态并重新读取 Task 投影；不得用时间戳补序。
11. 事件生产者由认证工作负载身份盖章，写入不可为空的 `producer_principal_ref`，并按事件类型限制：Worker 产生任务生命周期事实；Approval Service 产生审批决定事实；MCP Gateway/Reconciler 产生工具执行事实。模型返回的 JSON 永远不是权威事件。
12. Event Payload 只包含必要事实、稳定错误码和引用；凭据、隐藏思维链、原始附件和敏感全文不得进入事件。
13. 事件的 Major 版本代表不兼容语义。新增可选字段不得改变旧消费者对既有字段的解释。
14. Provider Session、Redis 队列和 SSE 游标都不是业务事实源；丢失后必须能从 PostgreSQL、Checkpoint 与 Outbox 恢复。
15. 生产者矩阵、版本/序号关系、命令摘要重算、命令与安全上下文绑定、幂等键摘要匹配和同版本槽位必须有负向契约与并发测试，不能只依赖代码约定。

## 原因

- 乐观版本检查可以明确拒绝过期客户端写入，避免静默覆盖。
- Inbox 唯一约束把重试和并发下的去重从“约定”提升为确定性控制。
- 至少一次投递符合 Outbox 与网络现实；去重和补洞比宣称恰好一次可验证。
- 分离 Checkpoint、Task 投影和 Event，既维持 LangGraph 唯一状态机，也支持查询与集成。

## 后果

正面：

- 重复命令、过期写入和重复事件都有稳定处理语义。
- SSE、评测和治理消费者可检测丢失，而不是悄悄接受不完整时间线。
- API 不暴露内部节点名，图结构可在兼容外部协议的前提下演进。

代价：

- Persistence 需要 Inbox、Outbox、Task Version 和每任务事件序号。
- Persistence 需要保存命令摘要、处理结果和同版本命令槽位。
- 消费者需要去重存储或可重建游标。
- 投影与 Checkpoint 出现差异时需要对账任务和诊断证据。

## 被拒绝方案

- API 直接 PATCH Task 状态：绕过 LangGraph 和业务不变量。
- 只使用 Redis Stream 作为事实源：Redis 丢失会丢业务事实。
- 宣称消息系统提供端到端恰好一次：不能覆盖消费者副作用与网络重连。
- 用时间戳排序事件：并发、时钟偏差和精度不足不能保证任务内顺序。
- 事件携带完整安全上下文：扩大泄漏面并让消费者误用身份声明。

## 验证

- `FP-FLOW-001`
- `FP-FLOW-009`
- `FP-DATA-001`
- `FP-DATA-002`
- `FP-DATA-003`
- `FP-OBS-001`
- `FP-OBS-002`
- `FP-SEC-005`
