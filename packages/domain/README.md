# flowpilot-domain

Pure Python domain values and invariants for FlowPilot. This package must not
import web, graph, ORM, Redis, MCP, policy, or provider SDK frameworks.

## Production dependency

| Dependency | Purpose | License | Alternative considered | Attack surface |
|---|---|---|---|---|
| `rfc8785` | Compute contract-defined RFC 8785 SHA-256 digests | Apache-2.0 | A local partial canonicalizer was rejected because approval and command integrity require complete RFC 8785 behavior | Processes schema-bounded JSON values only; callers must apply request-size limits before constructing domain objects |
