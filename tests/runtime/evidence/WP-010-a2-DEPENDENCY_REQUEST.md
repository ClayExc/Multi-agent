# DEPENDENCY_REQUEST

```text
REQUEST_ID=WP-010-a2-DR-001
FROM=S2-RUNTIME
TO=S5-CORE
CHAIN_ID=CHAIN-WP040-A0-REMEDIATION-01
STEP_ID=WP040-REM-02-S2
WORK_PACKAGE=WP-010
ATTEMPT_ID=WP-010-a2
RISK_CLASS=R2
STATUS=PENDING_CONSUMER
BASE_COMMIT=34bec05003cb59b3e16f1a16ae166b1f77465c46
UPSTREAM_HEAD=S6-DATA:e41f0266e6e588417332043b68a3309b2d40bcf7
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
```

## Requested shared-workspace change

1. Register `flowpilot-persistence` as an existing local dependency of
   `apps/worker` and preserve the exact S6 v2 port consumed by WP-010-a2.
2. Complete the pending WP-010-a1 registration of:
   - `apps/worker`
   - `packages/agent-runtime`
   - `packages/context`
   - `packages/graph`
   - `packages/model-gateway`
3. Lock the existing `langgraph>=1.2,<2` requirement and all FlowPilot
   workspace packages from a clean Python 3.12 environment.
4. Make the stable test entry include `tests/core`, `tests/runtime`, and the
   S6 persistence tests required by the authorization chain.
5. Preserve `make test-contract` as the frozen Contract Conformance gate.

No new third-party dependency is requested by WP-010-a2.

## Purpose

The Worker adapters consume S6 `DataUnitOfWorkFactory`,
`CheckpointRecord`, and `LeaseFence` directly. Workspace resolution must use
the accepted local S6 package so Checkpoint CAS, trusted Task thread lookup,
lease TTL, and run-generation fencing are tested under one dependency graph.

## Acceptance

- Root workspace resolves all S2 packages plus `flowpilot-persistence`.
- `make bootstrap` succeeds from a clean environment.
- `make test` includes Core, Runtime, and applicable Data suites.
- `make test-contract` emits the frozen rc2 conformance success line.
- Ruff and strict Mypy resolve the local packages without ad hoc source-path
  injection.

## Deferred observability follow-up

LangGraph Studio visibility is intentionally not part of this dependency
request. A later S2 debugging package should export the compiled production
graph with stable node and conditional-edge names, Interrupt/recovery paths,
and a sanitized state view so the multi-agent chain is observable rather than
a black box. Any Studio dependency or shared configuration must be requested
separately after the workspace closure is accepted.
