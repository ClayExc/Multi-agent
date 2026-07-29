# Database migrations

`0001_persistence_baseline.sql` is the M0 baseline.
`0002_checkpoint_sequence_cas.sql` is its only linear successor and upgrades
Checkpoint storage with a per-task sequence, deterministic lookup identity,
and database constraints required by atomic compare-and-swap. Both migrations
are atomic and repeatable. PostgreSQL roles are
`NOLOGIN`, `NOSUPERUSER`, and `NOBYPASSRLS`; deployments grant them only to
authenticated workload login roles outside this repository.

Local empty-volume startup mounts the baseline into the official PostgreSQL
initialization directory. Apply `0002` with the explicit command below until a
later integration work package owns migration-runner wiring. The `.down.sql`
files are development reset aids and are never mounted or run automatically.

Manual verification:

```text
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0001_persistence_baseline.sql
psql "$FLOWPILOT_DATABASE_ADMIN_URL" \
  -v ON_ERROR_STOP=1 \
  -f migrations/0002_checkpoint_sequence_cas.sql
```

Run both commands twice to verify repeatability. A statement failure rolls back
the entire migration because every file is enclosed by `BEGIN`/`COMMIT` and is
run with `ON_ERROR_STOP=1`.

The `0002` down migration fails before changing the schema when multiple tasks
share one `(tenant_id, thread_id)`, because the baseline uniqueness constraint
cannot be restored without data loss. After a successful development rollback,
reapply `0002` before running current persistence code.
