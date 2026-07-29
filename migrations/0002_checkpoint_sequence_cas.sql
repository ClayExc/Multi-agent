BEGIN;

DO $predecessor$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0001_persistence_baseline'
    ) THEN
        RAISE EXCEPTION
            '0002_checkpoint_sequence_cas requires 0001_persistence_baseline'
            USING ERRCODE = '55000';
    END IF;
END
$predecessor$;

INSERT INTO flowpilot.schema_migrations (migration_id, content_digest)
VALUES (
    '0002_checkpoint_sequence_cas',
    'sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc'
)
ON CONFLICT (migration_id) DO UPDATE
SET content_digest = EXCLUDED.content_digest
WHERE flowpilot.schema_migrations.content_digest = EXCLUDED.content_digest;

DO $migration_digest$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0002_checkpoint_sequence_cas'
          AND content_digest =
            'sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc'
    ) THEN
        RAISE EXCEPTION 'migration id is bound to another content digest'
            USING ERRCODE = '23514';
    END IF;
END
$migration_digest$;

ALTER TABLE flowpilot.checkpoints
    ADD COLUMN IF NOT EXISTS checkpoint_sequence bigint;

WITH ranked AS (
    SELECT
        ctid,
        row_number() OVER (
            PARTITION BY tenant_id, task_id
            ORDER BY run_generation, created_at, checkpoint_id
        ) AS checkpoint_sequence
    FROM flowpilot.checkpoints
)
UPDATE flowpilot.checkpoints AS checkpoint
SET checkpoint_sequence = ranked.checkpoint_sequence
FROM ranked
WHERE checkpoint.ctid = ranked.ctid
  AND checkpoint.checkpoint_sequence IS NULL;

ALTER TABLE flowpilot.checkpoints
    ALTER COLUMN checkpoint_sequence SET NOT NULL;

DO $checkpoint_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'flowpilot.checkpoints'::regclass
          AND conname = 'checkpoints_sequence_positive'
    ) THEN
        ALTER TABLE flowpilot.checkpoints
            ADD CONSTRAINT checkpoints_sequence_positive
            CHECK (checkpoint_sequence >= 1);
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'flowpilot.checkpoints'::regclass
          AND conname = 'checkpoints_task_sequence_key'
    ) THEN
        ALTER TABLE flowpilot.checkpoints
            ADD CONSTRAINT checkpoints_task_sequence_key
            UNIQUE (tenant_id, task_id, checkpoint_sequence);
    END IF;
END
$checkpoint_constraints$;

ALTER TABLE flowpilot.tasks
    DROP CONSTRAINT IF EXISTS tasks_tenant_id_thread_id_key;

DO $task_identity_constraint$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'flowpilot.tasks'::regclass
          AND conname = 'tasks_tenant_task_thread_key'
    ) THEN
        ALTER TABLE flowpilot.tasks
            ADD CONSTRAINT tasks_tenant_task_thread_key
            UNIQUE (tenant_id, task_id, thread_id);
    END IF;
END
$task_identity_constraint$;

DO $checkpoint_task_thread_fk$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'flowpilot.checkpoints'::regclass
          AND conname = 'checkpoints_task_thread_fk'
    ) THEN
        ALTER TABLE flowpilot.checkpoints
            ADD CONSTRAINT checkpoints_task_thread_fk
            FOREIGN KEY (tenant_id, task_id, thread_id)
            REFERENCES flowpilot.tasks (tenant_id, task_id, thread_id);
    END IF;
END
$checkpoint_task_thread_fk$;

DROP INDEX IF EXISTS flowpilot.checkpoints_latest_idx;
CREATE INDEX checkpoints_latest_idx
    ON flowpilot.checkpoints (
        tenant_id,
        task_id,
        thread_id,
        checkpoint_sequence DESC
    );

COMMIT;
