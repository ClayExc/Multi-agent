# flowpilot-application

Application use cases and versioned internal ports. The package depends only on
`flowpilot-domain` and Python protocols. S2 implements `ExecutionPort`; S6
implements `TaskRepositoryPort`, `CommandInboxPort`, and `UnitOfWork`.

Adapters must map provider, queue, and database failures to the stable errors
defined here without exposing raw exception text.

## Port semantics

- `ExecutionPort.submit` is idempotent by tenant and `command_id`. A duplicate
  submission returns a receipt with `disposition=duplicate`; it does not start a
  second workflow.
- A `UnitOfWork` atomically stores the command, tenant-scoped idempotency
  mapping, and `(tenant_id, task_id, expected_task_version)` reservation.
- Intake checks a valid command digest and security binding before opening the
  Unit of Work. Inside the transaction it checks idempotency first, then
  `command_id`, task version, and finally the version-slot reservation.
- Runtime dispatch happens after the accepted command commits. If dispatch
  fails, replaying the same command retries the idempotent Execution Port; a
  persisted receipt suppresses further dispatch.
