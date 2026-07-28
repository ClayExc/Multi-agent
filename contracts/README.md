# FlowPilot 契约基线

本目录保存跨模块、跨进程和评测使用的版本化契约。当前文件是架构阶段的 v1 候选基线，用来让后续代码和测试从同一 Schema 生成或校验对象。

`contract-set.v1.json` 是 M0 契约集清单。当前候选为 `1.0.0-rc.2`。S2、S3、S4、S5、S6 五条 Review 都对同一 `content_digest` 返回 `ACCEPT` 后，该 `candidate` 可作为实现基线；实现会话必须固定该摘要，变更时重新评审，且不得复制或扩展另一套公共对象。`frozen` 是更晚的发布级状态，还要求 Registry、Dataset、Fixture 与 Traceability 全部冻结；不能让尚未实现的 120/36 数据集反向阻塞代码启动。`status/reviews/frozen_at` 不进入内容摘要，避免写入评审结论后改变被评候选身份。

## 当前 Schema

| 文件 | 用途 |
|---|---|
| `jsonschema/agent-run-request.v1.schema.json` | Provider 中立的单次有界 Agent Runtime 请求 |
| `jsonschema/agent-run-result.v1.schema.json` | Provider 中立的 Agent Runtime 结果与稳定错误 |
| `jsonschema/security-context-ref.v1.schema.json` | 指向受信安全上下文的无凭据引用 |
| `jsonschema/task.v1.schema.json` | Task 的外部读模型与版本化状态投影 |
| `jsonschema/task-command.v1.schema.json` | API 写入的追加式命令意图 |
| `jsonschema/task-event.v1.schema.json` | Outbox/SSE 使用的至少一次任务事件 |
| `jsonschema/planned-action.v1.schema.json` | 模型提案转换后的不可变业务动作 |
| `jsonschema/approval.v1.schema.json` | 与动作摘要强绑定的审批 |
| `jsonschema/policy-decision.v1.schema.json` | PDP 的确定性授权、拒绝或审批要求 |
| `jsonschema/tool-request.v1.schema.json` | Worker/Runtime 向 MCP Gateway 的执行请求 |
| `jsonschema/tool-result.v1.schema.json` | Gateway 返回的执行、验证和不确定结果 |
| `jsonschema/context-envelope.v1.schema.json` | 每次 Agent/模型调用的分层上下文 |
| `jsonschema/audit-event.v1.schema.json` | 不可采样审计事件 |
| `jsonschema/security-event.v1.schema.json` | 不可采样的独立安全检测、影响与处置事件 |
| `jsonschema/evaluation-case.v1.schema.json` | 120 + 36 评测用例及功能关联 |
| `jsonschema/evaluation-dataset-manifest.v1.schema.json` | 评测 Case 文件、类别和哈希清单 |
| `jsonschema/evaluation-fixture-manifest.v1.schema.json` | 合成租户/主体 Fixture 清单 |
| `jsonschema/evaluation-registry.v1.schema.json` | 确定性断言与语义 Judge 注册表 |
| `jsonschema/feature-traceability.v1.schema.json` | 功能到测试、证据的机器追踪清单 |
| `jsonschema/contract-set.v1.schema.json` | 契约内容摘要、Review Attestation 与冻结状态 |

配套实例：

- `registries/evaluation-registry.v1.json`：断言与 Judge Rubric 的候选注册表。
- `registries/evaluation-dataset-manifest.v1.json`：120 + 36 Case 的候选文件清单；当前为空表示尚未实现。
- `registries/evaluation-fixture-manifest.v1.json`：不含真实 PII/凭据的合成 Fixture 清单。
- `docs/acceptance/traceability.v1.json`：功能、测试与证据映射的唯一机器事实源。

## 版本规则

- 新增可选字段：兼容变更，可以发布 Minor Schema 版本。
- 删除字段、改变类型/语义、收紧枚举：不兼容变更，发布新 Major 文件。
- 工具 Schema 变更后重新计算 `tool_schema_hash`。
- 影响动作语义或授权的字段必须进入 `action_digest`。
- `action_digest` 使用 RFC 8785 JSON Canonicalization Scheme 规范化后计算 SHA-256；计算对象为完整 `PlannedAction`，排除仅用于展示且在 Schema 中显式标记的字段。
- 代码模型不得比 Schema 更宽松；`additionalProperties: false` 不能在 Provider 适配层被移除。
- `TaskCommand` 是意图，不直接设置节点或终态；写入方必须提供 `expected_task_version`，重复命令按 `command_id` 和幂等键逻辑去重。
- `TaskCommand.command_digest` 的唯一前像是由 `command_type`、`tenant_id`、`task_id`、`actor`、`expected_task_version`、`payload` 组成的 JSON 对象，经 RFC 8785 规范化后计算 SHA-256；接收方必须重算，不能只校验字符串格式。
- `TaskCommand` 的 `tenant_id` 必须等于 `security_context.tenant_id`，`actor.id/type` 必须分别等于 `security_context.subject_id/type`；创建命令的 `payload.purpose` 还必须等于 `security_context.purpose`。任一错配均在写入 Inbox 前拒绝。
- `TaskCommand.command_digest` 必须先参与幂等键匹配；同键不同摘要是安全冲突。未命中幂等记录后才做版本检查和同版本槽位保留。
- `TaskEvent` 按任务维持严格递增 `sequence`，采用至少一次投递；多个事件可共享一个 `task_version`。消费者按 `event_id` 去重，并在序号缺口时重新读取 Task 投影。
- Task 事件只能由事件类型允许的认证服务端生产者盖章并携带 `producer_principal_ref`；模型 JSON 和 API 写请求都不是权威事件。
- `SecurityContextRef` 只携带不可伪造引用和哈希，不携带 Bearer Token、Cookie、上游凭据或完整声明；`data_classification_ceiling` 必填，任何 Context 层都必须同时受 Context Policy 与 SecurityContext 上限约束。
- `PolicyDecision` 由确定性 PDP 产生；obligation 强类型且无法执行时 fail-closed。模型只能提出动作，不能构造授权结果。
- M0 只支持单审批；多方审批不得用多个 `Approval v1` 私自拼装。
- Gateway 必须对 SecurityContext、PlannedAction、AgentPrincipal、PolicyDecision、Approval、摘要和策略版本执行跨对象语义绑定；SecurityContext 的引用与哈希都必须绑定 PolicyDecision，审批人必须与请求者不同。Schema 合法不能替代相等性、身份差异和摘要校验。
- `ToolResult.unknown` 不可重试且必须进入对账；只有带权威查询证据的 `confirmed_not_executed` 才能重试。结果的请求、策略和操作类型必须绑定原 ToolRequest；写动作的 `verified` 必须具有非空业务数据、证据引用和观察引用，且不允许使用 `not_applicable` 验证。
- Context 每层必须有非空内容和来源引用；L3～L6 不能伪装为受控指令。
- Agent Runtime 的 `tool_proposals` 不是权威 `PlannedAction`，可信字段由服务端重新构造并盖章。
- Trace 可采样；AuditEvent 与 SecurityEvent 均不可采样、不可包含隐藏思维链或明文密钥。
- 所有原始字节哈希源必须 UTF-8 无 BOM、LF 换行且 JSON 无重复键；`.gitattributes` 与 Conformance Gate 双重约束。
- Audit `event_hash` 使用 ADR-0004 的固定 RFC 8785 前像；链校验必须覆盖哈希重算、连续序号、同流前序哈希和可信 Tenant/Stream 绑定。

## 验收

实现阶段的 `make test-contract` 至少验证：

1. 所有 Schema 可被 Draft 2020-12 Validator 加载。
2. 官方示例通过。
3. 缺失必填字段、额外顶层字段、错误枚举和错误摘要被拒绝。
4. OpenAPI、Pydantic、事件和 MCP 暴露的字段与本目录兼容。
5. Schema 哈希变化会使原审批失效。
6. Dataset、Fixture、机器追踪清单与 Evaluation Registry 的跨文件 ID、哈希、配额和引用完整性通过。
7. 正例和负例覆盖状态组合、生产者矩阵、审批、obligation、未知工具结果、跨对象哈希/身份绑定、Audit 链、Review Attestation 和 Judge 边界。
