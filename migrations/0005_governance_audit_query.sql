BEGIN;

DO $predecessor$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM flowpilot.schema_migrations
                   WHERE migration_id = '0004_security_context_rls_binding') THEN
        RAISE EXCEPTION '0005_governance_audit_query requires 0004_security_context_rls_binding'
            USING ERRCODE = '55000';
    END IF;
END
$predecessor$;

INSERT INTO flowpilot.schema_migrations (migration_id, content_digest)
VALUES ('0005_governance_audit_query',
        'sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2')
ON CONFLICT (migration_id) DO UPDATE SET content_digest = EXCLUDED.content_digest
WHERE flowpilot.schema_migrations.content_digest = EXCLUDED.content_digest;

DO $digest$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM flowpilot.schema_migrations
                   WHERE migration_id='0005_governance_audit_query'
                     AND content_digest='sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2') THEN
        RAISE EXCEPTION 'migration id is bound to another content digest'
            USING ERRCODE = '23514';
    END IF;
END
$digest$;

CREATE OR REPLACE FUNCTION flowpilot.session_purpose() RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS $function$
    SELECT NULLIF(current_setting('flowpilot.purpose', true), '')
$function$;

CREATE OR REPLACE FUNCTION flowpilot.validate_governance_query_context()
RETURNS TABLE(validated boolean)
LANGUAGE sql STABLE AS $function$
    SELECT true
    FROM flowpilot.security_contexts sc
    WHERE sc.tenant_id = flowpilot.session_tenant_id()
      AND sc.context_ref = flowpilot.session_context_ref()
      AND sc.context_hash = flowpilot.session_context_hash()
      AND sc.subject_id = flowpilot.session_subject_id()
      AND sc.purpose = flowpilot.session_purpose()
      AND sc.active AND sc.revoked_at IS NULL
      AND sc.issued_at <= transaction_timestamp()
      AND sc.expires_at > transaction_timestamp()
$function$;

CREATE TABLE IF NOT EXISTS flowpilot.policy_versions (
    version text PRIMARY KEY,
    bundle_digest text NOT NULL CHECK (bundle_digest ~ '^sha256:[a-f0-9]{64}$'),
    active boolean NOT NULL,
    parent_version text,
    published_at timestamptz NOT NULL,
    revoked_at timestamptz,
    rollback_of text,
    CHECK (active <> (revoked_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS flowpilot.security_events (
    event_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    event_type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    trace_id text NOT NULL,
    correlation_id text NOT NULL,
    causation_id text,
    control_component text NOT NULL,
    control_rule_id text NOT NULL,
    control_rule_version text NOT NULL,
    reason_codes jsonb NOT NULL CHECK (jsonb_typeof(reason_codes)='array'),
    severity text NOT NULL,
    category text NOT NULL,
    control_outcome text NOT NULL,
    impact text NOT NULL,
    disposition text NOT NULL,
    data_classification text NOT NULL,
    audit_event_id text NOT NULL UNIQUE REFERENCES flowpilot.audit_events(event_id)
        DEFERRABLE INITIALLY DEFERRED,
    event_hash text NOT NULL CHECK (event_hash ~ '^sha256:[a-f0-9]{64}$'),
    thread_id text,
    task_id text,
    run_id text,
    policy_decision_id text,
    UNIQUE (tenant_id,event_id)
);

CREATE INDEX IF NOT EXISTS policy_versions_order_idx
    ON flowpilot.policy_versions (published_at DESC, version DESC);
CREATE INDEX IF NOT EXISTS policy_decisions_query_idx
    ON flowpilot.policy_decisions (tenant_id, created_at DESC, policy_decision_id DESC);
CREATE INDEX IF NOT EXISTS audit_events_query_idx
    ON flowpilot.audit_events (tenant_id, occurred_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS security_events_query_idx
    ON flowpilot.security_events (tenant_id, occurred_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS security_events_correlation_idx
    ON flowpilot.security_events (tenant_id, correlation_id, occurred_at DESC);

CREATE OR REPLACE VIEW flowpilot.governance_audit_events
WITH (security_barrier=true) AS
SELECT ae.tenant_id, ae.event_id,
       ae.event->>'event_type' AS event_type, ae.occurred_at,
       COALESCE(ae.event->>'trace_id',ae.event#>>'{trace,trace_id}') AS trace_id,
       ae.event->>'thread_id' AS thread_id, ae.event->>'task_id' AS task_id,
       ae.event->>'run_id' AS run_id, ae.event->>'correlation_id' AS correlation_id,
       ae.event->>'causation_id' AS causation_id, ae.event->>'action' AS action,
       ae.event->>'decision' AS decision,
       COALESCE(ae.event->'reason_codes','[]'::jsonb) AS reason_codes,
       ae.event->>'result' AS result,
       ae.event->>'data_classification' AS data_classification,
       ae.stream_id, ae.sequence, ae.event_hash, ae.previous_hash,
       ae.event->>'policy_decision_id' AS policy_decision_id,
       ae.event->>'policy_version' AS policy_version,
       ae.event->>'approval_id' AS approval_id,
       ae.event->>'action_digest' AS action_digest,
       ae.event->>'tool_execution_id' AS tool_execution_id,
       ae.event->>'security_event_id' AS security_event_id
FROM flowpilot.audit_events ae;

ALTER TABLE flowpilot.security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowpilot.security_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON flowpilot.security_events;
CREATE POLICY tenant_isolation ON flowpilot.security_events
USING (tenant_id = flowpilot.session_tenant_id())
WITH CHECK (tenant_id = flowpilot.session_tenant_id());

CREATE OR REPLACE FUNCTION flowpilot.reject_governance_mutation() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'governance facts are append-only' USING ERRCODE='55000';
END
$function$;

CREATE OR REPLACE FUNCTION flowpilot.append_security_event(
    p_tenant_id text,
    p_event_id text,
    p_audit_event_id text,
    p_event_hash text,
    p_event jsonb
) RETURNS void
LANGUAGE plpgsql AS $function$
DECLARE
    linked_security_event_id text;
BEGIN
    IF p_tenant_id IS DISTINCT FROM flowpilot.session_tenant_id() THEN
        RAISE EXCEPTION 'security event tenant does not match transaction tenant'
            USING ERRCODE='42501';
    END IF;
    SELECT event->>'security_event_id'
      INTO linked_security_event_id
      FROM flowpilot.audit_events
     WHERE tenant_id=p_tenant_id AND event_id=p_audit_event_id
     FOR SHARE;
    IF linked_security_event_id IS DISTINCT FROM p_event_id
       OR p_event->>'event_id' IS DISTINCT FROM p_event_id
       OR p_event->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_event->>'audit_event_id' IS DISTINCT FROM p_audit_event_id
       OR p_event->>'event_hash' IS DISTINCT FROM p_event_hash THEN
        RAISE EXCEPTION 'security and audit event association is invalid'
            USING ERRCODE='23514';
    END IF;
    INSERT INTO flowpilot.security_events (
        event_id,tenant_id,event_type,occurred_at,trace_id,correlation_id,
        causation_id,control_component,control_rule_id,control_rule_version,
        reason_codes,severity,category,control_outcome,impact,disposition,
        data_classification,audit_event_id,event_hash,thread_id,task_id,run_id,
        policy_decision_id
    ) VALUES (
        p_event_id,p_tenant_id,p_event->>'event_type',
        (p_event->>'occurred_at')::timestamptz,p_event->>'trace_id',
        p_event->>'correlation_id',p_event->>'causation_id',
        p_event->>'control_component',p_event->>'control_rule_id',
        p_event->>'control_rule_version',p_event->'reason_codes',
        p_event->>'severity',p_event->>'category',p_event->>'control_outcome',
        p_event->>'impact',p_event->>'disposition',
        p_event->>'data_classification',p_audit_event_id,p_event_hash,
        p_event->>'thread_id',p_event->>'task_id',p_event->>'run_id',
        p_event->>'policy_decision_id'
    );
END
$function$;

DROP TRIGGER IF EXISTS security_events_immutable ON flowpilot.security_events;
CREATE TRIGGER security_events_immutable BEFORE UPDATE OR DELETE
ON flowpilot.security_events FOR EACH ROW EXECUTE FUNCTION flowpilot.reject_governance_mutation();
DROP TRIGGER IF EXISTS policy_versions_immutable ON flowpilot.policy_versions;
CREATE TRIGGER policy_versions_immutable BEFORE UPDATE OR DELETE
ON flowpilot.policy_versions FOR EACH ROW EXECUTE FUNCTION flowpilot.reject_governance_mutation();

REVOKE ALL ON flowpilot.policy_versions, flowpilot.security_events FROM PUBLIC;
REVOKE ALL ON flowpilot.governance_audit_events FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.session_purpose() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.validate_governance_query_context() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.append_security_event(text,text,text,text,jsonb)
    FROM PUBLIC;
GRANT SELECT ON flowpilot.policy_versions, flowpilot.policy_decisions,
    flowpilot.audit_events, flowpilot.governance_audit_events, flowpilot.security_events
    TO flowpilot_api;
GRANT EXECUTE ON FUNCTION flowpilot.session_purpose(),
    flowpilot.validate_governance_query_context() TO flowpilot_api;
GRANT INSERT ON flowpilot.security_events TO flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.append_security_event(text,text,text,text,jsonb)
    TO flowpilot_gateway;

COMMIT;
