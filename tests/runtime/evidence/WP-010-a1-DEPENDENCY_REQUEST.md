# DEPENDENCY_REQUEST

```text
REQUEST_ID=WP-010-a1-DR-001
FROM=S2-RUNTIME
TO=S5-CORE
WORK_PACKAGE=WP-010
ATTEMPT_ID=WP-010-a1
RISK_CLASS=R2
STATUS=PENDING
BASE_COMMIT=93597a5023320d48875b292dc08106f03227a3fb
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
```

## Requested shared-workspace change

1. Add the following existing S2 packages to the root uv workspace and sources:
   - `apps/worker`
   - `packages/agent-runtime`
   - `packages/context`
   - `packages/graph`
   - `packages/model-gateway`
2. Lock `langgraph` with a Python 3.12-compatible `>=1.2,<2` constraint. The
   WP-010 validation environment currently provides `1.2.9`.
3. Make the stable test entry include `tests/runtime` without removing
   `tests/core`; either update the root pytest target set or the S5-owned
   `Makefile` command.
4. Preserve `make test-contract` as the existing Contract Conformance entry.

S2 does not request OpenAI, Claude, LiteLLM, PostgreSQL, Redis, or MCP SDK
dependencies in this attempt.

## Purpose

`langgraph` is required for the production `StateGraph` wrapper that owns
cross-node routing. The deterministic graph kernel remains a network-free
conformance fake; it must not become a second production state machine.

## Alternatives considered

- A permanent custom state-machine runner was rejected because it would violate
  ADR-0001.
- Provider SDK workflow/session objects were rejected because they are
  node-local and cannot own business recovery.
- Vendoring LangGraph was rejected because it would bypass the shared lock and
  supply-chain review.

## License and attack-surface review requested from S5

- Confirm package license and transitive licenses from locked metadata.
- Review serialization/checkpointer dependencies; WP-010 does not enable a
  third-party checkpointer in this request.
- Keep dynamic Provider SDK and prebuilt persistence adapters out of the base
  dependency set.
- Run vulnerability and lock reproducibility checks in the shared Workspace.

## Acceptance

- `make bootstrap` succeeds from a clean environment.
- `make test` includes Core and Runtime suites.
- `make test-contract` still emits the rc2 conformance success line.
- Ruff and strict Mypy can resolve all five S2 packages from the Workspace.
