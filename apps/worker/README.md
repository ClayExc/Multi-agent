# flowpilot-worker

Minimal worker assembly for the WP-010 runtime baseline.

`RuntimeExecutionAdapter` implements S5's `ExecutionPort` by placing a
tenant-scoped, command-idempotent envelope on an execution queue. `RuntimeWorker`
claims a fenced lease, advances the graph, checkpoints safe node boundaries,
and acknowledges or requeues the envelope based only on stable graph/runtime
semantics.

`PersistenceLeaseAdapter` and `PersistenceCheckpointAdapter` bridge the Graph
ports to S6 persistence v2. They resolve the trusted Task thread, bind
tenant/task/thread and run generation, execute checkpoint CAS under an active
lease fence, and map persistence failures to stable Graph errors.

The queue is a signal boundary, not a business fact source. The in-memory queue
remains a deterministic test fixture. Durable checkpoint and lease semantics
are supplied through the S6 `DataUnitOfWork`; a durable queue signal adapter is
still a later integration concern.
