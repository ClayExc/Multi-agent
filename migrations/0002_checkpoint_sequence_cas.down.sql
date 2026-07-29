BEGIN;

DO $thread_uniqueness$
BEGIN
    IF EXISTS (
        SELECT tenant_id, thread_id
        FROM flowpilot.tasks
        GROUP BY tenant_id, thread_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'cannot restore tenant/thread uniqueness while duplicate tasks exist'
            USING ERRCODE = '23505';
    END IF;
END
$thread_uniqueness$;

ALTER TABLE flowpilot.checkpoints
    DROP CONSTRAINT IF EXISTS checkpoints_task_thread_fk;
ALTER TABLE flowpilot.checkpoints
    DROP CONSTRAINT IF EXISTS checkpoints_task_sequence_key;
ALTER TABLE flowpilot.checkpoints
    DROP CONSTRAINT IF EXISTS checkpoints_sequence_positive;

DROP INDEX IF EXISTS flowpilot.checkpoints_latest_idx;

ALTER TABLE flowpilot.checkpoints
    DROP COLUMN IF EXISTS checkpoint_sequence;

ALTER TABLE flowpilot.tasks
    DROP CONSTRAINT IF EXISTS tasks_tenant_task_thread_key;

DO $legacy_thread_constraint$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'flowpilot.tasks'::regclass
          AND conname = 'tasks_tenant_id_thread_id_key'
    ) THEN
        ALTER TABLE flowpilot.tasks
            ADD CONSTRAINT tasks_tenant_id_thread_id_key
            UNIQUE (tenant_id, thread_id);
    END IF;
END
$legacy_thread_constraint$;

CREATE INDEX checkpoints_latest_idx
    ON flowpilot.checkpoints (
        tenant_id,
        thread_id,
        run_generation DESC,
        created_at DESC
    );

DELETE FROM flowpilot.schema_migrations
WHERE migration_id = '0002_checkpoint_sequence_cas';

COMMIT;
