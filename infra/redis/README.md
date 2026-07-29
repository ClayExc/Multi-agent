# Redis coordination boundary

Redis contains only tenant-scoped scheduling hints, cache entries, and rate
limits. It does not contain authoritative Task, Command, Approval, execution,
Checkpoint, Outbox, or Audit state.

The local container disables AOF and RDB persistence so loss/rebuild behavior
is exercised by default.
