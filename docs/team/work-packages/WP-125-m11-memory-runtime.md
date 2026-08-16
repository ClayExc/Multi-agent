# WP-125：Runtime、Checkpoint 与 Handoff 记忆集成

- 状态：BLOCKED
- Attempt：WP-125-a1
- Owner：S2-RUNTIME
- 风险：R2
- Feature：FP-FLOW-003、FP-CTX-001～004
- 依赖：WP-124
- 执行：ORDERED

把任务内 Turn/Snapshot/Manifest 接入 Worker 与 LangGraph：用户输入先持久化，Context Manifest
成功后才调用 Provider，Checkpoint 只保存最新记忆引用/Hash/预算计数，Handoff 重建 L3/L4。
摘要失败回退到上一 Snapshot 加最近消息。

写入 `apps/worker/**`、`packages/graph/**`、`packages/context/**`、`tests/runtime/**`。覆盖 50 轮、
Worker 重启、Redis 清空、旧 Worker fencing、历史 Snapshot/Checkpoint 重放、重复 Token 计费、
Manifest 故障和禁止字段。PASS 后交接 S5。
