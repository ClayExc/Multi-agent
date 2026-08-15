# WP-084：M8 租户与 RLS 绑定

## 元数据

- 状态：ACCEPTED_M8
- Attempt：WP-084-a1
- Owner：S6-DATA
- Reviewer：S4-QUALITY、S1-ARCH
- 风险：R2；跨租户成功为 P0
- Feature：FP-SEC-002、FP-OPS-001
- 依赖：WP-081、WP-082 Join
- 执行：与 WP-083 `PARALLEL`；S6 必须先完成 WP-081
- 子 Agent：`read-only/bounded-write`，最多 2 个；同一 Worktree 单写者

## 目标与输出

- 可撤销 SecurityContext 记录的 PostgreSQL Store/Adapter。
- 事务级 tenant/context/subject 绑定，提交、回滚、连接归还和恢复时确定性清理。
- 既存数据库角色若为 SUPERUSER/BYPASSRLS 必须拒绝或纠正后验证，不能静默沿用。
- 双租户 Fixture 与连接池复用、Worker 恢复黑盒。

## 允许路径

`packages/persistence/**`、`migrations/**`、`infra/**`、`.env.example`、`tests/data/**`。

## 必须测试

本租户正常读写；跨租户读写 0；缺失/伪造 tenant；不安全角色；连接池残留；事务回滚；
Context 撤销/过期；Migration up/down/replay；Redis 丢失不影响身份事实。

## 非目标

JWT/Claim 映射、API 会话、策略授权和 M9 审计存储。
