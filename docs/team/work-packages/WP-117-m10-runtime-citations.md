# WP-117：Runtime 知识查询与引用

- 状态：ACCEPTED_M10
- Attempt：WP-117-a1
- Owner：S2-RUNTIME
- 风险：R2
- Feature：FP-FLOW-003、FP-CTX-001、FP-MCP-001
- 依赖：WP-116
- 执行：ORDERED

让 LangGraph 通过现有 Gateway 调用知识工具，保存最小查询状态、稳定引用和安全摘要。无有效
证据时明确“不知道/需要更多信息”；模型不得生成未返回的企业事实。恢复、Handoff 和重试
必须重新验证引用，原始正文和候选列表不进入 Checkpoint、Trace 或 Provider Session。

写入 `apps/worker/**`、`packages/graph/**`、`packages/agent-runtime/**`、必要的
`packages/context/**`、`tests/runtime/**`。覆盖无结果、引用漂移、重试、Interrupt/Resume、
旧版本和恶意输出。PASS 后唤醒 S4 WP-118。
