# FlowPilot Policy

This package parses the exact public `PolicyDecision v1` shape and applies its
closed, strongly typed obligations. The PEP is default-deny:

- unknown, duplicate, malformed, conflicting, expired, or unsupported
  obligations fail closed;
- the subject reference and hash, authenticated Agent principal, tenant,
  task, action digest, tool operation, policy version, and expiry are bound;
- `deny` always overrides any other signal;
- `require_approval` remains authoritative until the Gateway validates the
  matching approved record.

Policy decisions are loaded through a trusted source Port. A
`ResolvedPolicyDecision` carries the stored RFC 8785 input preimage so the
declared `input_hash` can be recomputed instead of trusted as arbitrary JSON.
