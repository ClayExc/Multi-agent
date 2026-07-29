# Database migrations

`0001_persistence_baseline.sql` is an atomic, forward-only M0 migration. It can
be applied twice without changing existing facts. PostgreSQL roles are
`NOLOGIN`, `NOSUPERUSER`, and `NOBYPASSRLS`; deployments grant them only to
authenticated workload login roles outside this repository.

Local empty-volume startup mounts only the forward migration into the official
PostgreSQL initialization directory. The `.down.sql` file is a development
reset aid and is never mounted or run automatically.

Manual verification:

```text
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0001_persistence_baseline.sql
```

Run the same command twice to verify repeatability. A statement failure rolls
back the entire migration because it is enclosed by `BEGIN`/`COMMIT` and uses
`ON_ERROR_STOP=1`.
