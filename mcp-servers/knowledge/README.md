# FlowPilot Knowledge MCP fixture

`knowledge.search.v1` is a deterministic, read-only MCP fixture used to prove the
Gateway boundary. It accepts only an opaque capability handle, filters records by
the handle's trusted tenant, and has no write API, production credential, network
dependency, or durable fact store.
