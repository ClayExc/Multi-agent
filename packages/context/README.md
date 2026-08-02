# flowpilot-context

面向公共 `ContextEnvelope v1` 边界的确定性构建与 Handoff 重建。

该包：

- 使用来自 `flowpilot-domain` 的可信 `SecurityContextRef`；
- 始终各输出且仅输出一个 L0、L1 和 L2 层；
- 在调用 Provider 前强制执行数据分类与输入 Token 上限；
- 将 L3-L6 作为数据而非指令处理；
- 在 Handoff 时重建 Context，不复制对话记录或工具权限。

它不加载 Provider Session、凭据、原始附件或完整工具响应。
