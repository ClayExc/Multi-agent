# FlowPilot Tool Contracts

This package is the strict Python adapter for the public `PlannedAction`,
`ToolRequest`, and `ToolResult` v1 contracts. It does not define a second
public protocol.

The package:

- parses only the exact public fields and closed enums;
- recomputes `PlannedAction.digest()` with the shared domain RFC 8785 path;
- pins each tool to a canonical input/output schema hash;
- validates inputs and outputs with a deterministic JSON Schema subset;
- keeps stable error codes free of provider exceptions and secret material.

It has no network, persistence, policy, or credential access.

`flowpilot.worker-gateway.p1.v1` adds the Worker-facing `GatewayClientPort` and a
schema-pinned deterministic read fake. Calls contain only `ToolRequest` plus
thread/run correlation; authenticated workload and capability claims remain owned
by the Gateway transport. The fake enforces Tool Schema Pin, result binding and
tenant/tool/idempotency-key conflicts, and cannot execute writes.
