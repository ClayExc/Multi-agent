# flowpilot-graph

FlowPilot's LangGraph topology, deterministic node kernel, and recovery ports.

WP-010 and WP-012 provide:

- one `build_flowpilot_it_service_graph` factory shared by Worker and Studio;
- stable topology and graph identifiers guarded by a checked-in snapshot;
- a deterministic node kernel used by that wrapper and conformance tests;
- minimal checkpoint serialization that excludes provider sessions and secrets;
- lease/run-generation fencing requirements for the S6 persistence adapter;
- explicit interrupt and retry states; and
- deterministic parallel reducers;
- minimal VPN observation/result references and logical knowledge counters;
  and
- a default-deny `debug_projection` that exposes routing and recovery metadata
  without authority objects, raw context, credentials, or provider sessions.

The root Workspace locks LangGraph and the local Agent Server dependencies.
`langgraph.json` exposes the stable graph ID `flowpilot_it_service` through the
safe synthetic adapter only. Product execution continues to enter through the
Worker and its authoritative ports.
