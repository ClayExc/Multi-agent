# flowpilot-agent-runtime

与 Provider 无关的有界 Agent Runtime 模型、校验逻辑与确定性测试适配器。

Runtime 只负责一次有界调用，不拥有任务状态、审批、授权、Checkpoint 恢复或业务
终态决策。Provider Session 与 Run Reference 只用于诊断连续性提示，绝不能作为
Graph Checkpoint。
