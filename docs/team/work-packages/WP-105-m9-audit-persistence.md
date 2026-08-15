# WP-105：追加式 Audit 与 Security 存储

## 元数据

- 状态：BLOCKED
- Owner：S6-DATA
- Attempt：WP-105-a1
- 风险：R3
- Feature：FP-DATA-001、FP-OBS-002、FP-OBS-003
- 依赖：WP-104
- 执行：ORDERED
- 写入：`packages/persistence/**`、`migrations/**`、`tests/data/**`、`tests/data/evidence/WP-105-a1-HANDOFF.md`

## 主写目标

实现 PostgreSQL Audit/Security Event 追加式事实存储、RLS 查询、可信序号、双向关联和
完整性链，并实现 WP-104 查询 Port。

## 验收

- append 与业务关联在明确事务边界内；更新、删除、序号重复和链断裂失败关闭。
- RLS、连接池复用、错 tenant/context、撤销/过期身份和伪造游标成功数为 0。
- Redis 丢失后可从 PostgreSQL 重建查询游标/缓存，不改变审计事实。
- Migration 前向、失败回滚、down/up、Memory/Postgres 一致性和实库负例通过。
- Data 测试、Ruff、strict Mypy、Contract 和 Secret Scan 通过。

## 非目标

不实现 OPA/Secret Compose、Web 或产品执行器。完成后热继续 WP-106。
