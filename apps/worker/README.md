# flowpilot-worker

Minimal worker assembly for the WP-010 runtime baseline.

`RuntimeExecutionAdapter` implements S5's `ExecutionPort` by placing a
tenant-scoped, command-idempotent envelope on an execution queue. `RuntimeWorker`
claims a fenced lease, advances the graph, checkpoints safe node boundaries,
and acknowledges or requeues the envelope based only on stable graph/runtime
semantics.

The queue is a signal boundary, not a business fact source. The in-memory queue
is a deterministic test fixture; durable queue, checkpoint, and lease adapters
are supplied by later S6 integration.
