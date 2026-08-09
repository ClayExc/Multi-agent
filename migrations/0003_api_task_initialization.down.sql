BEGIN;

REVOKE INSERT ON flowpilot.tasks FROM flowpilot_api;

DELETE FROM flowpilot.schema_migrations
WHERE migration_id = '0003_api_task_initialization';

COMMIT;
