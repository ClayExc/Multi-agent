# FlowPilot Persistence

`flowpilot-persistence` implements the M0 data boundaries for:

- S5 `TaskRepositoryPort`, `CommandInboxPort`, and `UnitOfWork`.
- S3 execution ledger and reconciliation.
- S2 checkpoint, worker lease, fencing, and transactional outbox.
- Redis-backed signals that can be discarded and rebuilt from PostgreSQL facts.

PostgreSQL is the only business fact source. Every tenant transaction is bound
once through `flowpilot.tenant_id`; repositories reject attempts to switch the
tenant inside the same transaction. The migration enables and forces RLS on
tenant tables. Redis values contain only rebuildable scheduling hints.

The PostgreSQL adapter depends on a small injected async connection protocol.
This keeps the package importable before S5 accepts the driver dependency
request in `DEPENDENCY_REQUEST.md`; it does not turn the protocol into another
fact source. A future driver wrapper must use the locked Workspace versions and
must preserve the transaction and tenant-binding behavior tested here.

M0 intentionally does not include production HA, destructive migrations,
cross-region recovery, or a generic SQL escape hatch.
