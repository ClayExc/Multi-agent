# FlowPilot MCP Gateway

The M0 Gateway is the only business-tool entry point. It:

- resolves a trusted user `SecurityContextRef` and an authenticated workload;
- applies default-deny Tool Registry, Policy, obligation, and Approval checks;
- derives a deterministic execution identity and consumes the S6
  `DataUnitOfWork` ledger/Outbox Port;
- never retries an `UNKNOWN` write before authoritative reconciliation;
- verifies writes by readback and produces only closed `ToolResult v1` states;
- emits a structured lifecycle and separates sampled Trace from unsampled
  Audit/Security signals;
- exposes only a whitelist debug projection.

For P1 read-only knowledge access, the short-lived internal capability also binds
the trusted user subject/ACL memberships, authenticated workload principal,
tenant, Purpose, Scope and classification ceiling. The Knowledge MCP applies
those attributes before forming candidates; model arguments cannot supply or
override them.

The package contains no upstream enterprise client, production credential, or
private persistence implementation. Tool adapters, identity/policy sources,
credential broker, and signal sinks are injected Ports.
