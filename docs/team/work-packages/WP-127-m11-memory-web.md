# WP-127：上下文与短期记忆 Web

- 状态：BLOCKED
- Attempt：WP-127-a1
- Owner：S4-QUALITY
- 风险：R2
- Feature：FP-CTX-004、FP-UI-001、FP-OBS-002
- 依赖：WP-126
- 执行：ORDERED

实现中文任务内“上下文与短期记忆”面板：Snapshot 版本、覆盖轮次、待办、来源类型、过期时间、
逐层 Token、裁剪原因、恢复/回退状态和清理结果。默认不展示完整 Prompt、消息正文、被裁剪
内容、凭据或隐藏推理。

写入 `web/**`、`packages/observability/**`、`tests/experience/**`、`tests/acceptance/m11/**`。
覆盖会话失效、错租户、SSE 重放、可访问性、清理竞态和安全投影。PASS 后热继续 WP-128。
