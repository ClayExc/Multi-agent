# FlowPilot MCP Gateway

M0 Gateway 是业务工具的唯一入口，负责：

- 解析可信用户的 `SecurityContextRef` 和已认证的工作负载；
- 执行默认拒绝的 Tool Registry、Policy、obligation 和 Approval 检查；
- 派生确定性的执行身份，并使用 S6 提供的 `DataUnitOfWork` 账本/Outbox Port；
- 在完成权威对账前，绝不重试状态为 `UNKNOWN` 的写操作；
- 通过回读校验写入，并且只生成封闭状态集合中的 `ToolResult v1`；
- 发出结构化生命周期信号，区分可采样 Trace 与不可采样的 Audit/Security 信号；
- 仅暴露白名单调试投影。

对于 P1 只读知识访问，短期内部 capability 还会绑定可信用户主体及其 ACL
成员关系、已认证的工作负载主体、租户、Purpose、Scope 和数据分类上限。
Knowledge MCP 会先应用这些属性，再生成候选结果；模型参数既不能提供这些
属性，也不能覆盖它们。

本包不包含上游企业系统客户端、生产凭据或私有持久化实现。工具适配器、
身份/策略来源、凭据代理和信号接收端均通过 Port 注入。
