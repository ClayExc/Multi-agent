# flowpilot-worker

Minimal worker assembly for the WP-010 runtime baseline.

`RuntimeExecutionAdapter` implements S5's `ExecutionPort` by placing a
tenant-scoped, command-idempotent envelope on an execution queue. `RuntimeWorker`
claims a fenced lease, advances the graph, checkpoints safe node boundaries,
and acknowledges or requeues the envelope based only on stable graph/runtime
semantics.

`VpnReadOnlyGraph` is the P1 product composition for the deterministic
`intake -> clarify/interrupt -> knowledge -> respond` path. It resolves only
S5's redacted request observations, calls `knowledge.search.v1` only through
S3's `GatewayClientPort`, saves answer content through the opaque result
Artifact port, and persists only observation/result/reference metadata. The
parallel `service_read` branch is an explicit skip in this slice.

`PersistenceLeaseAdapter` and `PersistenceCheckpointAdapter` bridge the Graph
ports to S6 persistence v2. They resolve the trusted Task thread, bind
tenant/task/thread and run generation, execute checkpoint CAS under an active
lease fence, and map persistence failures to stable Graph errors.

The queue is a signal boundary, not a business fact source. The in-memory queue
remains a deterministic test fixture. Durable checkpoint and lease semantics
are supplied through the S6 `DataUnitOfWork`; a durable queue signal adapter is
still a later integration concern.

For local graph inspection, `flowpilot_worker.studio` binds the same graph
factory used by `LangGraphRuntime` to deterministic, synthetic nodes. The
`studio-safe` profile has no business writes or external network access and
fails closed when production credentials, endpoints, or profiles are present.
Its state emits only a default-deny debug projection suitable for viewing
routing, interrupts, handoff, retry, budget, checkpoint progression, logical
knowledge-call count, citation count, and the deterministic service-read skip.
