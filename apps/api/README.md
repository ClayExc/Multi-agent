# flowpilot-api

FastAPI adapter for liveness, versioned `TaskCommand` intake, and tenant-scoped
read-only Task projections. The process only calls Application ports. It cannot
mutate Task state, create authoritative events, connect to Provider/MCP
endpoints, or hold upstream credentials.

The module-level ASGI app is intentionally unconfigured: health remains
available, while command and task routes fail closed until composition supplies
Command Intake, Task Query, and Request Security ports.

## Runtime dependencies

| Dependency | Purpose | License | Alternative considered | Attack surface |
|---|---|---|---|---|
| `fastapi` | ASGI routing, OpenAPI generation, validation/error hooks | MIT | Starlette-only routing would require recreating schema and dependency integration | HTTP parsing and generated schemas; bounded by strict Pydantic models and explicit exception mapping |
| `pydantic` | Strict v1 request/response adapter models | MIT | Hand-written dictionary validation would make OpenAPI drift likely | Parses untrusted JSON; all nested models forbid extra fields and Domain invariants are rechecked |

`httpx` is a BSD-3-Clause development dependency used only for direct,
in-process ASGI contract tests.

## Minimum permissions

- Call the configured Application Command Intake and Task Query ports.
- Receive an authenticated identity from the configured Request Security port.
- No direct database, queue, Provider, MCP, policy store, Vault, or enterprise
  network access.
