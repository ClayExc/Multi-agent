# FlowPilot Knowledge MCP fixture

`knowledge.search.v1` is a deterministic, read-only MCP fixture used to prove the
Gateway boundary. Its P1 Schema Pin is fixed by `KNOWLEDGE_SCHEMA_PIN`; the legacy
M0 Pin fails closed.

Before any summary is inspected for matching, the adapter filters trusted metadata
by:

- user subject ACL membership and authenticated workload principal;
- tenant, Purpose and the `knowledge.search` capability Scope;
- data-classification ceiling and document effective/expiry timestamps.

The closed output contains only `source_ref`, document version, section, redacted
summary, content hash and classification. Internal ACLs never enter the result.
The fixture has no write API, production credential, network dependency or durable
fact store.
