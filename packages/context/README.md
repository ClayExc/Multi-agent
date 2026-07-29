# flowpilot-context

Deterministic construction and handoff rebuilding for the public
`ContextEnvelope v1` boundary.

The package:

- consumes the trusted `SecurityContextRef` from `flowpilot-domain`;
- always emits exactly one L0, L1, and L2 layer;
- enforces classification and input-token ceilings before provider use;
- treats L3-L6 as data rather than instructions; and
- rebuilds handoff context instead of copying a transcript or tool authority.

It does not load provider sessions, credentials, raw attachments, or complete
tool responses.
