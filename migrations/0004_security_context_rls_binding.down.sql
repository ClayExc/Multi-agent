BEGIN;

DO $linear_successor$
BEGIN
    IF EXISTS (
        SELECT 1 FROM flowpilot.schema_migrations
        WHERE migration_id = '0005_governance_audit_query'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade 0004 while 0005 exists'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id NOT IN (
            '0001_persistence_baseline',
            '0002_checkpoint_sequence_cas',
            '0003_api_task_initialization',
            '0004_security_context_rls_binding'
        )
    ) THEN
        RAISE EXCEPTION
            'rollback later migrations before 0004_security_context_rls_binding'
            USING ERRCODE = '55000';
    END IF;
END
$linear_successor$;

DO $stored_context_guard$
BEGIN
    IF EXISTS (SELECT 1 FROM flowpilot.security_contexts) THEN
        RAISE EXCEPTION 'cannot drop non-empty security context store'
            USING ERRCODE = '55000';
    END IF;
END
$stored_context_guard$;

REVOKE ALL ON flowpilot.security_contexts
    FROM flowpilot_api, flowpilot_worker, flowpilot_gateway;
REVOKE ALL ON FUNCTION flowpilot.validate_security_context()
    FROM flowpilot_api, flowpilot_worker, flowpilot_gateway;
REVOKE ALL ON FUNCTION flowpilot.session_tenant_id()
    FROM flowpilot_api, flowpilot_worker, flowpilot_gateway;
REVOKE ALL ON FUNCTION flowpilot.session_context_ref()
    FROM flowpilot_api, flowpilot_worker, flowpilot_gateway;
REVOKE ALL ON FUNCTION flowpilot.session_context_hash()
    FROM flowpilot_api, flowpilot_worker, flowpilot_gateway;
REVOKE ALL ON FUNCTION flowpilot.session_subject_id()
    FROM flowpilot_api, flowpilot_worker, flowpilot_gateway;

DROP FUNCTION IF EXISTS flowpilot.validate_security_context();
DROP TRIGGER IF EXISTS security_context_immutable_update
    ON flowpilot.security_contexts;
DROP TRIGGER IF EXISTS security_context_no_delete
    ON flowpilot.security_contexts;
DROP TABLE flowpilot.security_contexts;
DROP FUNCTION IF EXISTS flowpilot.prevent_security_context_mutation();
DROP FUNCTION IF EXISTS flowpilot.session_subject_id();
DROP FUNCTION IF EXISTS flowpilot.session_context_hash();
DROP FUNCTION IF EXISTS flowpilot.session_context_ref();
DROP FUNCTION IF EXISTS flowpilot.session_tenant_id();

DELETE FROM flowpilot.schema_migrations
WHERE migration_id = '0004_security_context_rls_binding';

COMMIT;
