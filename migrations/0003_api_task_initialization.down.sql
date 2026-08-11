BEGIN;

DO $linear_successor$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0004_security_context_rls_binding'
    ) THEN
        RAISE EXCEPTION
            'rollback 0004_security_context_rls_binding before 0003_api_task_initialization'
            USING ERRCODE = '55000';
    END IF;
END
$linear_successor$;

REVOKE INSERT ON flowpilot.tasks FROM flowpilot_api;

DELETE FROM flowpilot.schema_migrations
WHERE migration_id = '0003_api_task_initialization';

COMMIT;
