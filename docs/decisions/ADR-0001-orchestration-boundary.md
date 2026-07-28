# ADR-0001：业务编排、Agent Runtime 与模型网关边界

- 状态：Accepted
- 日期：2026-07-28

## 背景

项目同时选择 LangGraph、OpenAI/Claude Agents SDK 和 LiteLLM。三者都可能涉及路由、状态、工具或模型调用；如果没有明确边界，会出现双状态机、重复 Session、不可恢复 Handoff 和分散的计费/审计。

## 决策

1. LangGraph 是唯一跨业务节点的持久化状态机。
2. Agents SDK 只在单个有界节点内运行专业 Agent loop。
3. Manager 保持所有权时优先使用 agent-as-tool；Handoff 仅用于同一专业域内部的所有权转移。
4. `AgentRuntimePort` 隔离 OpenAI/Claude SDK；其唯一公共请求/结果由 `AgentRunRequest v1`、`AgentRunResult v1` 和 `docs/architecture/AGENT_RUNTIME.md` 定义，Provider 私有对象不进入领域或 Graph State。
5. `ModelGatewayPort` 隔离不需要 Agent loop 的分类、摘要、Rerank 和 Judge；LiteLLM 实现此端口。
6. 一个图节点一次只选择一个 Runtime/Provider。
7. Provider 切换发生在节点边界，重新构建 Context 并重新执行数据策略。
8. SDK Trace/Session 仅保存引用，用平台 `task_id/trace_id` 关联。
9. Runtime 返回的写工具调用只能是 `tool_proposal`，不是权威 `PlannedAction`；Application 层使用受信 Task、SecurityContext、Agent/Tool Registry 和策略版本重新构造动作。
10. Agent 身份、Provider 选择、工具范围和安全引用只能由认证的服务端包装层盖章。模型输出即使通过 JSON Schema，也不能成为这些字段的可信来源。
11. Runtime 失败映射为稳定平台错误码；只有 `failed_retryable` 可进入受预算约束的重试路径。
12. Fake、OpenAI 和 Claude Adapter 必须通过同一 Conformance Suite；必需 CI 门禁使用 Fake Adapter，不依赖真实 Provider 账户。

## 原因

- LangGraph 明确支持持久化、Interrupt 和故障恢复，适合业务长流程。
- Agents SDK 适合有明确工具和重复编排模式的有界 Agent run。
- LiteLLM 的统一模型路由不应替代 Agent SDK 生命周期，也不应决定业务权限。
- 单一业务状态所有者使测试、恢复和审计可以确定性表达。

## 后果

正面：

- 避免双状态源。
- 可替换 Provider。
- Handoff 权限边界清晰。
- 单 Agent 基线和多 Agent 可公平比较。

代价：

- 需要维护 Runtime Adapter 和统一结果契约。
- Provider 特有能力需显式映射。
- SDK Session 恢复与 LangGraph 恢复需要关联测试。
- Application 层需要把不可信工具提案转换为受信动作，并保存盖章来源。

## 被拒绝方案

- Agents SDK 作为整个业务流程控制器：难以统一跨 Provider 状态和企业审批。
- LangGraph 节点直接调用所有 Provider SDK：领域和图逻辑被 SDK 细节污染。
- 所有调用强制经 LiteLLM：可能与某些 SDK 生命周期、Session 或原生工具集成冲突。
- 两个 SDK 在同一节点共同管理对话：恢复和工具所有权不清。

## 验证

- `FP-FLOW-001`
- `FP-AGT-001`
- `FP-AGT-002`
- `FP-AGT-003`
- `FP-AGT-004`
- `FP-CTX-001`
