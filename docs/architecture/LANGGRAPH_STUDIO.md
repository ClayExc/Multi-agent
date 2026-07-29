# LangGraph Studio 非黑箱开发设计

## 1. 目标与边界

FlowPilot 使用 LangSmith Studio 作为 LangGraph 的本地可视化开发和故障定位界面。它需要让开发者看见图拓扑、实际经过的节点、Interrupt、Handoff、状态差异、重试和恢复，但不成为新的业务控制面。

关联功能：`FP-FLOW-001`、`FP-FLOW-004`、`FP-FLOW-005`、`FP-FLOW-006`、`FP-OBS-001`、`FP-OPS-002`。

必须保持：

1. LangGraph 仍是唯一跨业务节点的持久化状态机。
2. PostgreSQL Task、Checkpoint、Lease 和执行账本仍是恢复与副作用事实源。
3. Studio Thread/Run 只是开发调试游标，不是业务 Task、审批、租户或终态。
4. Studio 不能绕过 Application Port、MCP Gateway、策略、审批和账本。
5. Studio 状态不得包含明文凭据、原始附件、完整敏感资料或隐藏思维链。

## 2. 装配结构

仓库根部提供 `langgraph.json`，只声明稳定图入口和开发依赖位置。图入口位于 S2 所有的装配层，返回与 Worker 使用同一套编译函数生成的图，避免“Studio 图”和“生产图”分叉。

```text
langgraph.json
    → apps/worker Studio entrypoint
        → packages/graph graph factory
            → Application / Runtime / Checkpoint / Lease ports
                → studio-safe adapters
```

稳定图 ID 使用 `flowpilot_it_service`。节点 ID 是可观测 API：重命名需要迁移说明和拓扑快照更新，不能使用匿名 Lambda、动态随机名或 Provider 名拼接节点。

## 3. 两种开发配置

### `studio-safe`（默认）

- Fake Agent Runtime、Fake MCP、合成租户和脱敏 Fixture。
- 本地或内存适配器只用于无副作用演示；外部网络默认关闭。
- `LANGSMITH_TRACING=false` 时仍可连接本地 Agent Server，不上传 Trace。
- 不读取生产 `.env`，不允许生产凭据和真实 PII。

### `studio-integration`（显式启用）

- 连接本地 Compose 的 PostgreSQL、Redis、MCP Gateway 和策略服务。
- 只使用测试 Realm、测试租户、沙箱工具和一次性凭据。
- 写工具仍走审批、幂等、账本和回读；不能提供“调试直通”开关。
- 启动命令必须显式选择 Profile，不能由缺失配置自动升级。

生产环境不暴露 Studio 开发端口，也不允许通过 Studio 编辑业务线程状态。

## 4. 可视化投影

Studio 展示的状态是 `GraphState` 的安全投影，不是数据库对象的无筛选序列化。

| 视图 | 必须可见 | 必须隐藏 |
|---|---|---|
| 拓扑 | 稳定节点、条件边、并行分支、Handoff 边 | 动态凭据或租户私有配置 |
| 运行 | 当前节点、已走路径、重试次数、预算、停止原因 | 隐藏思维链、Provider 原始请求 |
| 恢复 | `task_id` 脱敏引用、checkpoint sequence、`run_generation`、Lease 状态 | 数据库连接、Lease Token 原文 |
| 审批 | Interrupt 原因、action digest 短引用、审批状态/过期状态 | 审批 Token、完整敏感参数 |
| Context | L0/L1/L2 是否存在、Token 预算、裁剪原因、来源引用 | 原始附件、未脱敏正文、完整会话转录 |
| 工具 | proposal/plan/policy/approval/ledger/result 阶段与稳定错误码 | 上游凭据、未脱敏工具结果 |

每个节点输出结构化 `debug_projection`，仅包含白名单字段。新增状态字段默认不可见，只有完成分类和脱敏测试后才能加入投影。

## 5. Interrupt、恢复与时间旅行

- 业务 HITL 使用动态 `interrupt()`；静态 breakpoint 只用于调试，不能替代审批。
- Interrupt 前的副作用必须为零或幂等。恢复会重新进入节点，因此节点内的前置逻辑必须可重放。
- Studio 中的 Fork/Edit/Re-run 只能作用于 `studio-safe` 或隔离的 `studio-integration` 测试数据。
- `thread_id` 必须由测试 Task 引用确定性派生或建立显式映射；不能把 Studio Thread ID 直接当作业务 `task_id`。
- 恢复界面必须能对齐 Studio checkpoint、FlowPilot checkpoint sequence 和 `run_generation`，发现不一致时失败关闭。

## 6. 验收

WP-012 至少交付：

1. `langgraph.json` 可由本地 Agent Server加载，稳定图 ID 可在 Studio Graph 模式展示。
2. 拓扑快照覆盖路由、并行只读、追问、审批 Interrupt、Handoff、重试/补偿和终止边。
3. 一个合成任务可以在 Studio 中暂停、恢复、故障重试和从 checkpoint 重放。
4. Studio 与 Worker 使用同一 graph factory；测试故意分叉入口时必须失败。
5. Secret/PII/隐藏思维链扫描为 0；新增状态字段未进入白名单时不可展示。
6. Studio 无法获得生产凭据、越权工具或绕过 Gateway 的网络路径。
7. Studio 状态编辑不改变业务事实源；对生产 Profile 的编辑尝试被拒绝并产生安全事件。

自动化证据包括图拓扑快照、Studio 启动 Smoke、Interrupt/Resume 轨迹、安全投影快照和 Secret Scan。截图可以作为学习证据，但不能替代结构化断言。

## 7. 责任

- S2-RUNTIME：graph factory、Studio entrypoint、安全状态投影和 Runtime 测试。
- S5-CORE：需要新增开发依赖时，作为 Python Workspace/Lock 单写者接入。
- S4-QUALITY：黑盒可见性、Secret/PII 和恢复演示验收。
- S1-ARCH：节点语义、事实源边界和完成定义裁决。

官方参考：

- [LangSmith Studio 本地接入](https://docs.langchain.com/oss/python/langgraph/studio)
- [LangGraph 应用结构与 langgraph.json](https://docs.langchain.com/oss/python/langgraph/application-structure)
- [LangGraph Interrupt](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
