# flowpilot-agent-runtime

Provider-neutral bounded Agent Runtime models, validation, and deterministic
test adapter.

The runtime owns one bounded call only. It does not own task state, approval,
authorization, checkpoint recovery, or business terminal decisions. Provider
sessions and run references are diagnostic continuity hints and must never be
used as graph checkpoints.
