# WP-124：短期记忆持久化与清理

- 状态：BLOCKED
- Attempt：WP-124-a1
- Owner：S6-DATA
- 风险：R2
- Feature：FP-CTX-002/004、FP-DATA-001、FP-SEC-003
- 依赖：WP-123
- 执行：ORDERED

实现 Conversation Turn、Working Memory Snapshot 与 Context Manifest 的 PostgreSQL Adapter、
线性可逆 Migration、强制 RLS、幂等追加、Snapshot CAS、消息高水位、TTL/终态清理和删除证明。
Redis 仅作可重建调度。

写入 `packages/persistence/**`、`migrations/**`、`infra/**`、`tests/data/**`。验证跨租户 0、
连接复用、并发压缩、重复消息、回滚、Redis 清空、Migration 中断与删除后残留 0。PASS 后
交回 S2 WP-125。
