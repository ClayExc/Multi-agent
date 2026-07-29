# flowpilot-application

Application use cases, validated declarative Domain Pack loading, and versioned
internal ports. S2 implements `ExecutionPort`; S6 implements
`TaskRepositoryPort`, `TaskQueryPort`, `CommandInboxPort`, and `UnitOfWork`.

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
- `TaskQueryPort` must scope every lookup by `(tenant_id, task_id)` and must
  never return a projection for a different tenant or task.
- Domain Packs are data-only directories. Loading uses bounded files, exact
  fields, path containment, and a safe YAML loader that rejects aliases; no
  module is imported from a pack.

## Dependency record

| Dependency | Use | License | Alternative | Attack surface and control |
| --- | --- | --- | --- | --- |
| PyYAML | Parse declarative Domain Pack YAML | MIT | JSON-only packs or a bespoke parser | Parser resource and object-construction risks are bounded by file-size limits, exact schemas, `SafeLoader`, and rejection of aliases |
| types-PyYAML (development) | Strict Mypy coverage for PyYAML | Apache-2.0 | Local protocol stubs | Build-time only; excluded from production wheels |
