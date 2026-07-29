# flowpilot-graph

FlowPilot's LangGraph topology, deterministic node kernel, and recovery ports.

WP-010-a1 provides:

- a `StateGraph` wrapper that is the only production cross-node router;
- a deterministic node kernel used by that wrapper and conformance tests;
- minimal checkpoint serialization that excludes provider sessions and secrets;
- lease/run-generation fencing requirements for the S6 persistence adapter;
- explicit interrupt and retry states; and
- deterministic parallel reducers.

The external `langgraph` distribution is not yet present in the shared lock.
The exact dependency and workspace integration request is recorded with the
WP-010 evidence. S5 must accept that request before the package can be installed
through the root Workspace.
