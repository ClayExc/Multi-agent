# ADR-0002：安全副作用、审批与幂等协议

- 状态：Accepted
- 日期：2026-07-28

## 背景

工单创建、通知发送和权限申请无法与平台数据库形成单个分布式 ACID 事务。LangGraph Interrupt 恢复会从节点开头重跑；网络超时又可能产生“上游已成功、平台未知”的状态。只有重试次数不足以避免重复写。

## 决策

1. 模型只生成 `PlannedAction`，确定性代码规范化并计算 `action_digest`。
2. 审批绑定主体、租户、任务、动作摘要、工具 Schema、原始 `policy_decision_id`、策略版本和过期时间。
3. 参数或权限相关字段变化后旧审批失效。
4. 所有写动作只由 MCP Gateway 执行。
5. Gateway 在执行前同时校验用户主体和服务端盖章的 Agent 主体，重新授权并验证职责分离；任一主体被拒绝时采用 deny-overrides。
6. Gateway 为 `(tenant_id, tool, idempotency_key)` 建唯一执行账本。
7. 相同逻辑动作在恢复和重试中复用同一幂等键。
8. 上游返回后执行回读验证。
9. 超时且无法判断结果时进入 `UNKNOWN`，`retryable=false` 且必须携带对账计划；只有权威确认“未执行”后，才允许用原幂等键进入新的重试尝试。
10. 业务事务与事件通过 Transactional Outbox 提交。
11. 补偿显式建模，不伪装成数据库回滚。
12. M0 只支持单审批：`minimum_approvers=1`。`approved` 必须具有非空审批人、决策时间且 `separation_of_duties_result=true`；Gateway 还必须确定性验证 `approver_id != requester_id`，不能把布尔字段当成职责分离证据。多方审批留到 v2 的显式 `ApprovalSet/ApprovalDecision[]`，不得用多条 v1 记录拼装。
13. `PolicyDecision.obligations` 使用按名称判别的强类型参数。未知、重复、畸形、冲突、超出实现能力或 PEP 无法执行的 obligation 一律 fail-closed。
14. `ToolResult` 的状态与字段组合是封闭协议：`verified` 必须有匹配回读且无错误；`failed_retryable` 必须证明未发送或未执行；`failed_final` 不可重试；`unknown` 只能对账。
15. SecurityContext、Agent/Tool Registry 和策略记录只有在来源认证、租户/用途/有效期/哈希校验全部通过后才可信；“JSON 通过 Schema”不构成可信来源。
16. Gateway 在执行前必须完成跨对象绑定：SecurityContext 的租户/主体对应 PlannedAction 的租户/请求者，`context_ref` 与 `context_hash` 同时对应 PolicyDecision 的 `subject_ref` 与 `subject_context_hash`；认证 Agent Principal 对应动作和 PolicyDecision 中的 Agent；重新计算的 `action_digest` 对应 PolicyDecision、Approval 和 ToolRequest；策略要求审批时 Approval 必须完整匹配。任一错配 fail-closed 并产生稳定安全事件。
17. `ToolResult` 的 `request_id`、`policy_decision_id` 和 `operation` 必须绑定原 ToolRequest/PlannedAction。`operation=write` 且状态为 `verified` 时，必须返回非空业务数据、`evidence_ref`、`verification.observed_ref` 和匹配的权威回读，不能使用 `verification.method=not_applicable`；`confirmed_not_executed` 只能来自带证据引用的上游幂等查询或业务键查询。
18. Trace、AuditEvent 和 SecurityEvent 分流。Trace 可采样；AuditEvent 与 SecurityEvent 都不可采样。被阻断的审计记录必须关联独立 SecurityEvent，二者只保存脱敏引用。

## 原因

- 审批绑定自然语言描述无法阻止批准后参数替换。
- 数据库唯一约束可在并发和重放下提供强幂等入口。
- 回读可区分返回成功与业务状态真正生效。
- `UNKNOWN` 状态承认远程副作用的现实，避免重复创建。
- Outbox 解决业务状态已提交但消息未投递的问题。

## 后果

正面：

- 可证明重复写入为零。
- 审批不可被参数替换或跨动作重放。
- 恢复与重试行为可预测。
- 工具、策略和审计形成完整证据链。

代价：

- 每个写工具都需要业务唯一标记或查询接口。
- Gateway 需要执行账本和 Reconciler。
- 某些上游系统无法确认结果时必须人工对账。
- M0 不提供会签、或签和法定人数审批；需要该能力时必须升级显式契约。

## 被拒绝方案

- 只依赖 LangGraph Checkpoint 防重复：Checkpoint 与远程副作用不是同一事务。
- 每次重试生成新幂等键：会把同一逻辑动作变成多次写入。
- 超时直接重试：无法判断上游是否已执行。
- 审批只保存 `approval_id`：不能证明批准了哪些具体参数。
- 让 Action Agent 自己判断审批是否有效：模型不是授权器。
- 把任意 obligation 作为自由 JSON 交给 PEP：无法证明它被正确执行。
- 用 AuditEvent 的自由文本代替 SecurityEvent：无法形成独立检测、影响与处置证据。

## 验证

- `FP-MCP-003`
- `FP-MCP-004`
- `FP-MCP-005`
- `FP-APR-001`
- `FP-APR-003`
- `FP-SEC-001`
- `FP-SEC-004`
- `FP-OBS-002`
- `FP-OBS-003`
- `FP-DATA-001`
