# PostgreSQL boundary

- Business facts live in the `flowpilot` schema.
- Tenant tables use both `ENABLE ROW LEVEL SECURITY` and
  `FORCE ROW LEVEL SECURITY`.
- Runtime roles are `NOLOGIN`, `NOSUPERUSER`, and `NOBYPASSRLS`.
- The trusted adapter sets one transaction-local `flowpilot.tenant_id` and
  rejects tenant switching.
- PlannedAction, PolicyDecision, Approval, Checkpoint, and Audit rows are
  append-only or have narrowly guarded state changes.

Superuser/migrator access is not an application path. Break-glass access must
use a separate login, short-lived authorization, and an audit process supplied
by a later operations work package.
