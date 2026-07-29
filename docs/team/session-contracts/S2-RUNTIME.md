# SC-S2-RUNTIME-v2：流程与 Agent Runtime

## 会话声明

```text
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-010
FEATURE_IDS=FP-FLOW-001,FP-FLOW-002,FP-AGT-002,FP-CTX-001
WRITE_SCOPE=apps/worker/**,packages/graph/**,packages/agent-runtime/**,packages/model-gateway/**,packages/context/**,tests/runtime/**,WP-010授权共享文件
```

- 契约状态：READY_ON_BASELINE_SYNC；WP-011 H1 已接受
- 当前工作：[WP-010 Runtime 基线](../work-packages/WP-010-runtime-bootstrap.md)
- 激活条件：S2/S3/S4/S5/S6 已对同一 rc2 `content_digest` 全部 `ACCEPT`，S1 完成实现基线激活提交并为本会话建立独立 Worktree；发布级 `frozen` 不前置阻塞实现。

## 使命

把 S5 提供的版本化应用命令转化为可恢复的 LangGraph 任务执行，维护确定性路由、Context 构建、统一 Agent Runtime Port、Provider 适配和 Worker 恢复。

## 决策权

S2 可以：

- 决定 Graph 节点拆分、Reducer、Checkpoint 接入和 Runtime Adapter 细节。
- 选择确定性算法、Fake Runtime Fixture 和内部错误映射。
- 对不可实现的公共契约提交 RFC。

S2 不可以：

- 修改 `contracts/**`、ADR 或验收状态。
- 直连上游 MCP、企业数据库、企业网络或密钥。
- 让模型决定授权、审批、租户或任务终态。
- 把 Provider Session、凭据、SDK 对象或完整文档写入 Graph State。

## 输入与输出

| 类型 | 内容 |
|---|---|
| 输入 | 评审时为同一 rc2 `content_digest`；实现时为 Task/Command/Event、ContextEnvelope、AgentRunRequest/Result、ToolRequest/Result、S5 Application Port 与 WP-010 |
| 输出给 S5 | Execution Port 实现、确定性运行结果、Task Event 提案和稳定 Runtime 错误 |
| 输出给 S3 | ToolRequest、安全上下文引用、动作与审批需求、稳定错误语义 |
| 输出给 S4 | Task Event/SSE、Fake Runtime 场景、Trace 属性、Context Manifest |
| 输出给 S1 | 契约可实现性结论、RFC、状态迁移风险和交接证据 |

## 工程约定

1. 不复制 S5 的领域对象；跨会话只消费公共契约和显式 Application Port。
2. LangGraph 是唯一跨业务节点状态机；Task 只是投影。
3. Graph 节点小、结构化、可重放；确定性边负责终态、预算、审批和重试。
4. Interrupt 前不发生非幂等副作用。
5. 一个节点一次只使用一个 Provider；Provider Session 不等于 Checkpoint。
6. Handoff 重新构建 ContextEnvelope 和工具集合。
7. 相同命令与固定 Fake Runtime 应产生相同逻辑轨迹。
8. 外部异常映射为稳定错误码，原始异常只进入脱敏诊断。

## 必须交付的测试

- 正常：S5 Application Port → Graph/Fake Runtime → 确定性运行结果。
- 边界：空上下文、等待状态、预算边界和并行 Reducer。
- 失败：版本冲突、Provider 结构错误、预算耗尽和不可恢复错误。
- 安全：越权工具提案、伪造安全上下文、敏感字段进入 State 被拒绝。
- 恢复：重复 Command、Interrupt、Worker 重启和图版本迁移。

## 当前审查任务

在 `REVIEW_ONLY` 阶段只返回以下结论，不写仓库：

1. 针对 `flowpilot-m0-contracts-v1-rc2` 的精确 `content_digest`，确认 Task 状态组合、Command 去重/版本/同版本并发和 Event 生产者矩阵可实现。
2. 确认 ContextEnvelope 强制 L0/L1/L2 且 Handoff 可重建。
3. 确认 AgentRunRequest/Result 足以隔离 OpenAI/Claude SDK，ToolResult 状态不会导致盲重试。
4. 结论为 `ACCEPT`、`ACCEPT_WITH_RFC` 或 `REJECT`；非 `ACCEPT` 必须给出具体 Schema 路径、兼容性和建议。

## 完成定义

- WP-010 的全部命令真实通过。
- Runtime conformance、Graph 恢复和 Worker 重投测试齐备。
- 没有公共契约复制、工具旁路或状态权威漂移。
- 交接由 S1/S4 复核后，相关功能才可进入下一状态。
