# DEPENDENCY_REQUEST WP-021-DR-001

- Requester: `S6-DATA`
- Owner: `S5-CORE`
- Work Package: `WP-021`
- Status: `REQUESTED`

## Requested Workspace changes

Add `packages/persistence` as a uv workspace member and lock:

- `sqlalchemy[asyncio]>=2.0,<3`
- `psycopg[binary,pool]>=3.2,<4`
- `redis>=5.2,<6`

Alembic is not required for this first forward-only SQL migration. It should
only be added if S5 and S1 choose it as the shared migration runner.

## Purpose

- SQLAlchemy provides the application-facing async transaction boundary.
- Psycopg provides PostgreSQL protocol and pool support.
- redis-py implements rebuildable queue signals and cache coordination.

Until accepted, `flowpilot-persistence` exposes injected connection/client
protocols and has no import-time dependency on these libraries.

## License, alternatives, and attack surface

- SQLAlchemy: MIT; alternative is direct Psycopg, but that would couple every
  repository to a driver API.
- Psycopg: LGPL-3.0 with exceptions; alternative is asyncpg, which would add a
  second SQL parameter/result convention.
- redis-py: MIT; alternative is a custom RESP client, rejected because it would
  add security- and reliability-sensitive protocol code.
- All database parameters remain bound values. No caller-provided SQL, role,
  table, schema, or Redis key fragment is accepted.
- Pools must clear transaction state before reuse. Credentials remain
  environment references and are never written to checkpoints, Redis, logs, or
  test evidence.
