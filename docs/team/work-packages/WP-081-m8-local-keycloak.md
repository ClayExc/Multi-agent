# WP-081：M8 本地 Keycloak 基座

## 元数据

- 状态：ACCEPTED_M8
- Attempt：WP-081-a1
- Owner：S6-DATA
- Reviewer：S3-PLATFORM、S4-QUALITY
- 风险：R2
- Feature：FP-SEC-001、FP-SEC-007、FP-OPS-001
- 依赖：WP-080
- 执行：与 WP-082 `PARALLEL`，路径互斥
- 子 Agent：`read-only/bounded-write`，最多 2 个；同一 Worktree 单写者

## 目标与输出

- 可重复导入的本地 Realm、双租户用户/角色、Web/API/Worker/Gateway Client。
- Authorization Code + PKCE、Client Credentials、刷新、撤销和健康检查 Fixture。
- Compose、环境变量模板和 Secret-safe 演示配置；不提交真实密码或 Client Secret。

## 允许路径

`infra/**`、`.env.example`、`tests/data/**`。需要 Migration 或 Persistence 变更时留给
WP-084；不得修改安全验证器或 API。

## 复用与禁止重复

复用现有 Keycloak 26.1.4、Compose 网络和 PostgreSQL/Redis 基线；不重跑 M7 Provider、
知识执行器或完整 RELEASE。子任务分别处理 Realm Fixture、Compose/健康检查和安全负例，
不得重复读取全仓文档。

## 必须测试

- 空卷导入、幂等重启、双租户登录、刷新/撤销和两个服务 Client。
- 错 Client/audience/redirect URI、缺 Secret、过期会话失败关闭。
- Secret Scan 为 0；容器和卷清理可证明。

## 非目标

生产 IdP/HA/TLS、JWT 验证、SecurityContext 映射、RLS、M9 Policy/DLP。
