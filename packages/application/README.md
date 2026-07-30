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
- `TaskQueryService` opens a read Unit of Work for each lookup so tenant
  binding, transaction cleanup, and connection lifecycle remain adapter-owned.
- `RequestReferenceResolverPort` receives a tenant/task/message/security-context
  binding and returns only a digest-bound, redacted observation. The
  Application service recomputes required fields from the Domain Pack and
  rejects tenant, purpose, classification, reference, or digest mismatches.
- `ResultArtifactPort.put` atomically deduplicates by
  `(tenant_id, idempotency_key)`. Same-digest replay returns the original
  `result_ref`; a different digest conflicts. Receipts never expose result
  content, so the public Task projection only carries `result_ref`.
- `flowpilot.reference-ports.p1.v1` is an internal Python port version. It does
  not widen the public `TaskCommand` or Task JSON Schema.
- Domain Packs are data-only directories. Loading uses bounded files, exact
  fields, path containment, and a safe YAML loader that rejects aliases; no
  module is imported from a pack. The v2 manifest additionally validates
  synthetic request observations, knowledge samples, and per-case citation
  expectations.

## Dependency record

| Dependency | Use | License | Alternative | Attack surface and control |
| --- | --- | --- | --- | --- |
| PyYAML | Parse declarative Domain Pack YAML | MIT | JSON-only packs or a bespoke parser | Parser resource and object-construction risks are bounded by file-size limits, exact schemas, `SafeLoader`, and rejection of aliases |
| types-PyYAML (development) | Strict Mypy coverage for PyYAML | Apache-2.0 | Local protocol stubs | Build-time only; excluded from production wheels |
