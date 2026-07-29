# M0 data/control-plane Compose

From the repository root:

```text
Copy-Item .env.example .env
docker compose --env-file .env -f infra/compose/compose.yaml config
docker compose --env-file .env -f infra/compose/compose.yaml up -d
docker compose --env-file .env -f infra/compose/compose.yaml ps
```

The PostgreSQL migration runs only when the named volume is empty. To verify a
forward migration again without deleting facts, run the `psql` command from
`migrations/README.md`.

Run the real RLS and expiry-binding negative cases after PostgreSQL is healthy:

```text
docker compose --env-file .env -f infra/compose/compose.yaml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - \
  < tests/data/integration/verify_postgres.sql
```

Redis is deliberately configured without AOF or RDB persistence. Clearing or
replacing it must not affect Task, Checkpoint, Outbox, Approval, or execution
facts. Rebuild scheduling hints from PostgreSQL through
`RedisCoordinationAdapter.rebuild`.

The checked-in credentials are obvious local placeholders. `.env` is ignored.
Production identity, secrets, TLS, backup, HA, and external audit anchoring are
outside WP-021-a1.
