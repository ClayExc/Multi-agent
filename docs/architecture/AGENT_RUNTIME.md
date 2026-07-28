# FlowPilot Agent Runtime Port v1

## 1. 定位

Agent Runtime Port 把 LangGraph 节点与 OpenAI Agents SDK、Claude Agent SDK 和确定性 Fake Runtime 隔离。它只描述一次有界 Agent 调用，不拥有跨节点业务状态、授权、审批或任务终态。

机器契约：

- `contracts/jsonschema/agent-run-request.v1.schema.json`
- `contracts/jsonschema/agent-run-result.v1.schema.json`
- `contracts/jsonschema/context-envelope.v1.schema.json`

关联功能：`FP-AGT-001`、`FP-AGT-002`、`FP-AGT-003`、`FP-AGT-004`、`FP-CTX-001`。

## 2. 端口

```python
class AgentRuntimePort(Protocol):
    async def run(self, request: AgentRunRequest) -> AgentRunResult: ...
```

适配器：

- `FakeAgentRuntimeAdapter`
- `OpenAIAgentsRuntimeAdapter`
- `ClaudeAgentRuntimeAdapter`

领域层只依赖端口和值对象，不导入任何 Provider SDK 类型。Provider 原生异常、Run、Message、Session 和 Tool 对象不得越过适配器边界。

## 3. 请求不变量

1. 每次调用只有一个已选择的 Provider 和模型。
2. `task_id`、`tenant_id`、Agent 身份、工具范围和 Provider 数据策略由确定性应用代码填充。
3. `context` 必须包含且仅包含一个 L0、L1、L2；Handoff 后重新构建。
4. `security_context` 必须由受信服务创建并在调用前重新校验哈希、租户、用途和有效期。
5. `allowed_tools` 是本次调用的上限；适配器不能自行发现或增加工具。
6. `propose_write` 只允许模型返回提案，不能执行副作用。
7. `budget` 是硬上限。Provider 配置不得放宽轮次、工具次数、Token、成本或超时。
8. `session_ref` 是无凭据引用，不是业务 Checkpoint；缺失或失效时可从 Context 重新开始本节点。
9. 冗余关联字段必须在调用 Provider 前执行确定性一致性校验：
   - Request 与 Context 的 `task_id` 必须一致；Request、Context 和 SecurityContext 的 `tenant_id` 必须一致。
   - `agent.id` 必须等于 `context.agent_id`。
   - SecurityContext 的主体/用途必须与当前 Task 请求者和 Context 用途一致。
   - 选定 Provider 必须位于 `context.policy.provider_allowlist`。
   - Context 各层数据等级不得超过 Context/SecurityContext 的 classification ceiling。
   - Context 的估算/实际输入 Token 不得超过 Context Policy 和 Request 的最大输入预算。
10. 任一一致性检查失败都不调用 Provider，返回 `failed_final + RUNTIME_REQUEST_INCONSISTENT` 并记录稳定原因码。

以下信息不得进入请求：

- Bearer Token、Cookie、API Key、私钥或上游凭据。
- Provider 私有 Session 对象。
- 原始附件、未裁剪全文或隐藏思维链。
- 未经 L1 安全视图允许的数据或工具。

## 4. 结果不变量

1. `completed` 必须具有符合请求中 `output_schema` 的结构化输出，且 `error=null`。
2. 其他状态必须 `structured_output=null` 并携带稳定平台错误。
3. 只有 `failed_retryable` 可以返回 `error.retryable=true`。
4. `public_reasoning_summary` 只包含可展示的理由摘要，不保存隐藏思维链。
5. `tool_proposals` 不是 `PlannedAction`。模型只能提出工具、操作、参数、资源、用途和证据引用。
6. Application 层必须根据受信 Task、SecurityContext、Agent Registry、Tool Registry 和策略版本重新构造 `PlannedAction`。
7. `tool_call_refs` 只能引用经 MCP Gateway 执行的调用。
8. `handoff_proposal` 只是建议；LangGraph 确定性边决定是否允许，并重新生成 Context 与工具集。
9. `session_ref`、`provider_run_ref` 仅用于诊断或节点级连续性，不参与权限和业务恢复判断。

## 5. 稳定错误语义

| 错误码 | 可重试 | 语义 |
|---|---:|---|
| `RUNTIME_PROVIDER_UNAVAILABLE` | 是 | Provider 瞬时不可用；仍受图重试预算 |
| `RUNTIME_REQUEST_INCONSISTENT` | 否 | Request、Context、安全主体、Agent、Provider 或预算绑定不一致 |
| `RUNTIME_INVALID_OUTPUT` | 否 | 输出不能通过冻结 Schema |
| `RUNTIME_BUDGET_EXHAUSTED` | 否 | 任一硬预算耗尽 |
| `RUNTIME_GUARDRAIL_BLOCKED` | 否 | 内容或行为 Guardrail 阻断 |
| `RUNTIME_TOOL_SCOPE_VIOLATION` | 否 | 提议或调用未授权工具 |
| `RUNTIME_DATA_POLICY_DENIED` | 否 | Provider 或数据策略拒绝 |
| `RUNTIME_INTERNAL` | 否 | 未分类内部错误；默认不重试 |

Provider 原始错误只能进入脱敏诊断引用，不能作为 API 错误码或路由条件。

## 6. 可信来源

JSON 通过 Schema 不代表内容可信：

- Agent ID/版本来自已发布 Agent Registry，由 Runtime 包装层盖章。
- Provider/模型来自 Model Gateway 的数据策略和路由决定。
- Tool Schema Hash 来自已发布 Tool Registry。
- SecurityContext 来自认证服务的不可伪造引用。
- 模型输出中的租户、请求者、Agent、策略、审批和终态字段全部忽略。

模型生成的写提案转换为 `PlannedAction` 时，确定性代码必须覆盖身份与版本字段，再计算 `action_digest`。

## 7. 恢复与 Handoff

- LangGraph Checkpoint 保存 Runtime 请求所需的最小业务引用，不保存 Provider 原生对象。
- 节点重试可以复用 `session_ref`，但必须重新校验 Context、安全上下文、Provider 数据策略和预算。
- Provider 切换只能发生在节点边界，创建新的请求与 Trace 事件。
- Handoff 不跨审批或执行边界；目标 Agent 只能获得新 ContextEnvelope 中允许的字段。
- Runtime 失败不能直接把 Task 标记为终态；确定性图路由根据错误码、预算和业务规则决定重试、失败或升级。

## 8. Conformance 要求

Fake、OpenAI 和 Claude 适配器必须运行同一组契约测试：

| 测试 | 必须断言 |
|---|---|
| 合法结构化结果 | 请求/结果通过 v1 Schema，输出 Schema Hash 匹配 |
| Provider 错误映射 | 原始异常映射为稳定错误码，不泄漏原文 |
| 工具范围 | 未列入 `allowed_tools` 的提案或调用被拒绝 |
| 写提案边界 | Runtime 不能返回权威 PlannedAction、PolicyDecision 或 Approval |
| Context 门禁 | 缺失/重复 L0～L2 时不调用 Provider |
| 跨对象绑定 | Task/Tenant/Agent/Purpose/Provider/Token 任一错配时不调用 Provider并返回稳定错误 |
| 数据策略 | Restricted 数据不能路由到未批准 Provider |
| 预算 | 任一上限耗尽即停止，不能由 Provider 放宽 |
| Session 隔离 | Session 丢失不影响从 Checkpoint 重建本节点 |
| Handoff 过滤 | 禁止字段和上游工具权限不进入目标调用 |
| 敏感信息 | 请求、结果、Trace 和错误中 Secret Scan 为 0 |

CI 的必需 conformance 使用 Fake Runtime，不依赖真实 Provider 账户。真实 Provider 适配测试可以单独运行，但不能替代确定性门禁。
