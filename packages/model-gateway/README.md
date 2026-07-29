# flowpilot-model-gateway

Provider-neutral routing seam for model calls that do not require an Agent
loop. The M0 implementation is a deterministic, network-free fake and routing
policy. LiteLLM integration remains behind this port and is not part of
WP-010-a1.

The gateway cannot widen a Context provider allowlist, classification ceiling,
or token/cost budget.
