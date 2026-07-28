# WP-010：Runtime、Graph 与 Worker 基线

## 元数据

- 状态：BLOCKED
- 责任会话：S2-RUNTIME
- 评审会话：S1-ARCH、S4-QUALITY、S5-CORE
- 功能 ID：FP-FLOW-001、FP-FLOW-002、FP-AGT-002、FP-CTX-001
- 依赖工作包：S2/S3/S4/S5/S6 对同一 WP-000 `content_digest` 全部 ACCEPT、实现基线激活提交；公共 Python Workspace 依赖 WP-011
- 目标分支：`codex/s2/wp-010-runtime-bootstrap`

## 目标

- 建立 LangGraph、Agent Runtime、Context、Model Gateway 与 Worker 的最小可恢复骨架。
- 建立 Provider 中立 Runtime Port、确定性 Fake、Checkpoint/Interrupt 和 Handoff 边界。
- 用恢复与架构测试阻止状态权威、工具旁路和 Provider Session 漂移。

## 非目标

- 领域模型、Application Use Case、FastAPI 或公共 Python Workspace。
- 真实 Provider 账户调用或完整 IT 服务闭环。
- 直连 PostgreSQL、Redis、OPA、MCP 或企业网络。
- 修改公共契约、授权结果或持久化实现。

## 允许修改路径

- `apps/worker/**`
- `packages/graph/**`
- `packages/agent-runtime/**`
- `packages/model-gateway/**`
- `packages/context/**`
- `tests/runtime/**`

不得修改 `pyproject.toml`、`uv.lock`、`Makefile`；依赖变化通过 WP-011/S5 交接。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| `contract-set.v1.json` | reviewed implementation baseline | S1-ARCH |
| Task / Command / Event、Context、Agent Runtime、ToolRequest/Result | v1 | S1-ARCH |
| Application/Execution Port | M0 internal | S5-CORE / WP-011 |
| Python Workspace 与测试命令 | M0 | S5-CORE / WP-011 |
| Persistence Adapter Port | M0 internal | S6-DATA / WP-021 |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| Runtime Execution Adapter | M0 internal | S5 |
| Fake Runtime Conformance Fixture | M0 | S4 |
| ToolRequest 与安全上下文引用 | v1 | S3 |
| Worker Lease/Checkpoint 需求 | M0 internal | S6 |
| Task Event/SSE 运行事实 | v1 | S4、S5 |

## 架构与安全约束

- LangGraph 是唯一跨业务节点状态机；Task 只作为外部投影。
- Graph State 不存 Provider Session、Token、原始附件或 SDK 对象。
- Interrupt 前不得发生非幂等副作用；Handoff 必须重建 Context 和工具集合。
- Fake Runtime 必须确定性且不依赖网络。
- 所有工具执行只产生 Tool Proposal/ToolRequest，不绕过 S3 Gateway。

## 实施内容

1. 创建 Worker、Graph、Runtime、Context 与 Model Gateway 包骨架。
2. 定义 S5 Execution Port 的实现适配层和稳定 Runtime 错误。
3. 创建 Fake Runtime、最小 ContextEnvelope 构建器和 Provider Adapter Fake。
4. 建立 Checkpoint、Interrupt、Handoff、并行 Reducer 与重试补偿骨架。
5. 添加 Graph 状态、预算、Context、Provider 隔离和恢复测试。
6. 通过 WP-011 提出的公共命令运行测试；未实现命令必须明确失败。

## 必须测试

- 正常：S5 Application Port → Graph/Fake Runtime → 确定性结果。
- 边界：最小 Context、预算边界、等待状态和并行 Reducer。
- 失败：Provider 结构错误、预算耗尽、不可恢复错误和稳定错误映射。
- 安全：越权工具提案、伪造安全上下文、敏感字段进入 State 被拒绝。
- 恢复：Interrupt、Worker 重启、Checkpoint 恢复和图版本迁移。

## 验收命令

```bash
make test
make test-contract
```

若 WP-011 尚未提供命令或依赖，记录为依赖阻塞，不得以手工检查冒充通过。

## 完成定义

- Runtime Conformance、Graph 恢复、Context 和 Worker 重投测试通过。
- 未复制 S5 领域对象、公共 Schema 或 S6 Persistence 实现。
- 没有工具旁路、Provider Session 事实化或状态权威漂移。
- S1/S4/S5 完成跨角色审查。
