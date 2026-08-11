# M0 数据面与控制面 Compose

在仓库根目录执行：

```text
Copy-Item .env.example .env
docker compose --env-file .env -f infra/compose/compose.yaml config
docker compose --env-file .env -f infra/compose/compose.yaml up -d
docker compose --env-file .env -f infra/compose/compose.yaml ps
```

PostgreSQL 会在命名卷为空时按 `0001 -> 0002 -> 0003 -> 0004` 运行正向迁移。如果需要
在不删除业务事实的情况下再次验证，请执行 `migrations/README.md` 中的 `psql`
命令。

PostgreSQL 健康后，运行真实的 RLS 与过期时间绑定负向用例：

```text
docker compose --env-file .env -f infra/compose/compose.yaml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - \
  < tests/data/integration/verify_postgres.sql
```

M8 的身份绑定还应使用真实 PostgreSQL 运行可撤销 SecurityContext、事务级
tenant/context/subject 绑定、连接复用清理、跨租户读取为零和 Redis 丢失恢复负例：

```text
$env:FLOWPILOT_TEST_DATABASE_URL = "postgresql://<migrator>:<password>@127.0.0.1:<port>/<database>"
uv run python tests/data/integration/verify_security_context.py
```

该验证脚本会分别切换到最小权限 API/Worker 角色；连接使用迁移账号仅用于建立连接和
验证不安全数据库角色会被持久化适配器拒绝。业务 UoW 必须使用可信
`TrustedSecurityContext`，不能从浏览器 Tenant Header 构造绑定。

Redis 被有意配置为不启用 AOF 或 RDB 持久化。清空或替换 Redis 不得影响 Task、
Checkpoint、Outbox、Approval 或执行事实。调度提示应通过
`RedisCoordinationAdapter.rebuild` 从 PostgreSQL 重建。

Keycloak 首次空卷启动时从 `infra/keycloak/flowpilot-local-realm.json` 导入 M8 本地
Realm；后续重启会保留 `keycloak-data` 并跳过已存在 Realm。健康检查访问容器内部
management port 9000 的 `/health/ready`，不把 management port 暴露到宿主机。
Realm 用户密码与 Worker/Gateway Client Secret 只从 `.env` 注入；提交的 JSON 只含
环境占位符。动态登录、刷新/撤销、服务 Client 与安全负例使用
`tests/data/integration/verify_keycloak.py` 验证。

仓库中提交的凭据是显而易见的本地占位值，`.env` 已被忽略。生产身份、密钥、
TLS、备份、高可用和外部审计锚定不属于当前本地 Compose 的范围。
