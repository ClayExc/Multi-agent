# FlowPilot Tool Contracts

本包是公共 `PlannedAction`、`ToolRequest` 和 `ToolResult` v1 契约的严格
Python 适配器，不会另行定义第二套公共协议。

本包负责：

- 只解析精确的公共字段和封闭枚举；
- 通过共享领域层的 RFC 8785 路径重新计算 `PlannedAction.digest()`；
- 将每个工具固定到规范的输入/输出 Schema Hash；
- 使用确定性的 JSON Schema 子集校验输入和输出；
- 保持错误码稳定，且不包含 Provider 异常或密钥材料。

本包不具备网络、持久化、策略或凭据访问能力。

`flowpilot.worker-gateway.p1.v1` 增加了面向 Worker 的 `GatewayClientPort`，
以及由 Schema Pin 固定的确定性只读 fake。调用内容只包含 `ToolRequest` 和
thread/run 关联信息；已认证工作负载和 capability 声明仍由 Gateway transport
管理。该 fake 会强制校验 Tool Schema Pin、结果绑定，以及租户/工具/幂等键
冲突，并且不能执行写操作。
