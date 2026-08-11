# WP-084-a1 S6-DATA Checkpoint

- `CHAIN_ID`: `CHAIN-M8-IDENTITY-TENANCY-01`
- `ATTEMPT_ID`: `WP-084-a1-checkpoint`
- `BASE_HEAD`: `a1a0360153ec9f1ca1c9009056ae3ba483b2a22f`
- `FULL_GATE`: `EXPECTED_BLOCKED`
- `STATUS`: implementation checkpoint; not a WP-084 PASS Handoff

## Implemented checkpoint

- PostgreSQL-backed revocable SecurityContext Source/Adapter.
- Transaction-local tenant, context, context-hash, and subject binding with deterministic cleanup.
- Runtime database-role rejection for `SUPERUSER` or `BYPASSRLS`.
- Linear migration `0004` with forced RLS, immutable revocation, safe-role correction, guarded down/replay behavior, and Compose initialization.
- Redis remains rebuildable coordination state; PostgreSQL remains the fact source.

## Reused verification evidence

- Data suite: `101 passed`.
- Real PostgreSQL: `stored=2 idempotent=1 cross_tenant_success=0 unsafe_role_rejected=1 pool_residual=0 revoked=1 expired=1 redis_rebuilt=0`.
- Contract Conformance: PASS (`20` schemas, `35` cases, `52` features).
- Ruff: PASS.
- Persistence and new evidence strict Mypy: PASS.
- Full repository diagnostic: `1379 passed, 1 skipped, 4 failed`; all four failures are the external migration-verifier blocker below.

## External blockers

1. `S7_WP040_VERIFIER_FIXED_0003`: the S7-owned WP-040 verifier fixes the authorized migration Head and hashes at `0003`, so it rejects the authorized linear `0004` migration (`4 failures`). S6 did not modify `scripts/integration/**` or `tests/integration/**`.
2. `DEPENDENCY_LOCK_PENDING_WP083`: the input baseline declares PyJWT in `packages/security`, while the root `uv.lock` is not synchronized. Locked workspace gates fail before execution; the root lock is outside this S6 write scope.

No formal WP-084 PASS Handoff is asserted. Completion awaits the external verifier and dependency-lock owners.
