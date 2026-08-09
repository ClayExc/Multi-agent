# M0 数据面与控制面 Compose

在仓库根目录执行：

```text
Copy-Item .env.example .env
docker compose --env-file .env -f infra/compose/compose.yaml config
docker compose --env-file .env -f infra/compose/compose.yaml up -d
docker compose --env-file .env -f infra/compose/compose.yaml ps
```

PostgreSQL 会在命名卷为空时按 `0001 -> 0002 -> 0003` 运行正向迁移。如果需要
在不删除业务事实的情况下再次验证，请执行 `migrations/README.md` 中的 `psql`
命令。

PostgreSQL 健康后，运行真实的 RLS 与过期时间绑定负向用例：

```text
docker compose --env-file .env -f infra/compose/compose.yaml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - \
  < tests/data/integration/verify_postgres.sql
```

Redis 被有意配置为不启用 AOF 或 RDB 持久化。清空或替换 Redis 不得影响 Task、
Checkpoint、Outbox、Approval 或执行事实。调度提示应通过
`RedisCoordinationAdapter.rebuild` 从 PostgreSQL 重建。

仓库中提交的凭据是显而易见的本地占位值，`.env` 已被忽略。生产身份、密钥、
TLS、备份、高可用和外部审计锚定不属于 WP-021-a1 的范围。
