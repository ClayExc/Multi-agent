# Offline observability boundary

`SignalRouter` provides the deterministic test seam for `FP-OBS-001`:

- Trace signals may be sampled.
- Audit and SecurityEvent signals must be retained.
- Each signal keeps tenant, trace, task, and correlation identifiers.
- Trace, Audit, and SecurityEvent use distinct destinations.
- A blocked Audit event and its SecurityEvent must link to one another in both
  directions.
- Payloads containing secret-like material or forbidden raw reasoning fields are
  rejected before they become evidence.

This package does not configure an OpenTelemetry SDK or any production storage.
Those integrations wait for WP-010/WP-011/WP-020/WP-021 handoffs.
