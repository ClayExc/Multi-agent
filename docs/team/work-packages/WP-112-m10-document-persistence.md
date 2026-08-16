# WP-112：知识文档事实与 RLS

- 状态：BLOCKED
- Attempt：WP-112-a1
- Owner：S6-DATA
- 风险：R2
- Feature：FP-DATA-001、FP-SEC-002/003
- 依赖：WP-111
- 执行：ORDERED

实现 PostgreSQL 文档、版本、ACL、章节、索引任务和 Outbox 事实表；使用线性、可逆 Migration、
强制 RLS、受信事务 Context 与追加版本语义。导入/更新/撤销/删除和任务 Outbox 必须原子，
旧版本不可原地改写。

写入 `packages/persistence/**`、`migrations/**`、`tests/data/**`。验证跨租户读写为 0、连接复用
不残留 Context、重复命令、并发版本冲突、回滚、过期/撤销和 Migration 中断。PASS 后热继续
WP-113。
