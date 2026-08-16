BEGIN;
DO $guard$
BEGIN
    IF EXISTS (SELECT 1 FROM flowpilot.schema_migrations
               WHERE migration_id > '0005_governance_audit_query') THEN
        RAISE EXCEPTION 'cannot downgrade while successor migrations exist'
            USING ERRCODE='55000';
    END IF;
    IF EXISTS (SELECT 1 FROM flowpilot.security_events)
       OR EXISTS (SELECT 1 FROM flowpilot.policy_versions) THEN
        RAISE EXCEPTION 'cannot remove non-empty governance facts'
            USING ERRCODE='55000';
    END IF;
END
$guard$;
DROP VIEW flowpilot.governance_audit_events;
DROP TRIGGER policy_versions_immutable ON flowpilot.policy_versions;
DROP TRIGGER security_events_immutable ON flowpilot.security_events;
DROP TABLE flowpilot.security_events;
DROP TABLE flowpilot.policy_versions;
DROP FUNCTION flowpilot.reject_governance_mutation();
DROP FUNCTION flowpilot.append_security_event(text,text,text,text,jsonb);
DROP FUNCTION flowpilot.validate_governance_query_context();
DROP FUNCTION flowpilot.session_purpose();
DELETE FROM flowpilot.schema_migrations WHERE migration_id='0005_governance_audit_query';
COMMIT;
