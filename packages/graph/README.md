# flowpilot-graph

FlowPilot 的 LangGraph 拓扑、确定性节点内核与恢复 Port。

WP-010 与 WP-012 提供：

- Worker 与 Studio 共享的 `build_flowpilot_it_service_graph` Factory；
- 由仓库内 Snapshot 保护的稳定拓扑与 Graph 标识符；
- 供该 Wrapper 和一致性测试使用的确定性节点内核；
- 排除 Provider Session 与密钥的最小 Checkpoint 序列化；
- S6 持久化适配器必须遵守的租约/run-generation fencing 要求；
- 显式的 Interrupt 与重试状态；
- 确定性并行 Reducer；
- 最小 VPN 观测/结果引用与逻辑知识调用计数器；
- 默认拒绝的 `debug_projection`：只暴露路由和恢复元数据，不包含权限对象、
  原始 Context、凭据或 Provider Session。

根 Workspace 锁定 LangGraph 与本地 Agent Server 依赖。`langgraph.json` 仅通过
安全的合成适配器暴露稳定 Graph ID `flowpilot_it_service`。产品执行仍必须从 Worker
及其权威 Port 进入。
