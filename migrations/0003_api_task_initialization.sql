BEGIN;

DO $predecessor$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0002_checkpoint_sequence_cas'
    ) THEN
        RAISE EXCEPTION
            '0003_api_task_initialization requires 0002_checkpoint_sequence_cas'
            USING ERRCODE = '55000';
    END IF;
END
$predecessor$;

INSERT INTO flowpilot.schema_migrations (migration_id, content_digest)
VALUES (
    '0003_api_task_initialization',
    'sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2'
)
ON CONFLICT (migration_id) DO UPDATE
SET content_digest = EXCLUDED.content_digest
WHERE flowpilot.schema_migrations.content_digest = EXCLUDED.content_digest;

DO $migration_digest$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0003_api_task_initialization'
          AND content_digest =
            'sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2'
    ) THEN
        RAISE EXCEPTION 'migration id is bound to another content digest'
            USING ERRCODE = '23514';
    END IF;
END
$migration_digest$;

GRANT INSERT ON flowpilot.tasks TO flowpilot_api;

COMMIT;
