BEGIN;

CREATE SCHEMA IF NOT EXISTS flowpilot;

CREATE TABLE IF NOT EXISTS flowpilot.schema_migrations (
    migration_id text PRIMARY KEY,
    content_digest text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO flowpilot.schema_migrations (migration_id, content_digest)
VALUES (
    '0001_persistence_baseline',
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
        WHERE migration_id = '0001_persistence_baseline'
          AND content_digest =
            'sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc'
    ) THEN
        RAISE EXCEPTION 'migration id is bound to another content digest'
            USING ERRCODE = '23514';
    END IF;
END
$migration_digest$;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowpilot_api') THEN
        CREATE ROLE flowpilot_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowpilot_worker') THEN
        CREATE ROLE flowpilot_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowpilot_gateway') THEN
        CREATE ROLE flowpilot_gateway NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowpilot_publisher') THEN
        CREATE ROLE flowpilot_publisher NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOBYPASSRLS;
    END IF;
END
$roles$;

CREATE OR REPLACE FUNCTION flowpilot.current_tenant_id()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('flowpilot.tenant_id', true), '')
$function$;

CREATE OR REPLACE FUNCTION flowpilot.prevent_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'immutable relation % rejects %', TG_TABLE_NAME, TG_OP
        USING ERRCODE = '55000';
END
$function$;

CREATE TABLE IF NOT EXISTS flowpilot.tasks (
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    thread_id text NOT NULL,
    status text NOT NULL,
    version bigint NOT NULL CHECK (version >= 0),
    run_generation bigint NOT NULL CHECK (run_generation >= 0),
    projection jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, task_id),
    UNIQUE (tenant_id, thread_id),
    CHECK (projection ->> 'tenant_id' = tenant_id),
    CHECK (projection ->> 'task_id' = task_id),
    CHECK ((projection ->> 'version')::bigint = version),
    CHECK ((projection ->> 'run_generation')::bigint = run_generation)
);

CREATE TABLE IF NOT EXISTS flowpilot.task_commands (
    command_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    command_type text NOT NULL,
    expected_task_version bigint,
    idempotency_key text NOT NULL,
    command_digest text NOT NULL,
    command jsonb NOT NULL,
    accepted_at timestamptz NOT NULL,
    execution_receipt jsonb,
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, command_id),
    CHECK (expected_task_version IS NULL OR expected_task_version >= 0),
    CHECK (command ->> 'command_id' = command_id),
    CHECK (command ->> 'tenant_id' = tenant_id),
    CHECK (command ->> 'task_id' = task_id),
    CHECK (command ->> 'command_digest' = command_digest),
    CHECK (command ->> 'idempotency_key' = idempotency_key)
);

CREATE TABLE IF NOT EXISTS flowpilot.task_command_slots (
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    slot_version bigint NOT NULL CHECK (slot_version >= -1),
    command_id text NOT NULL,
    PRIMARY KEY (tenant_id, task_id, slot_version),
    UNIQUE (tenant_id, command_id),
    CONSTRAINT task_command_slot_command_fk
        FOREIGN KEY (tenant_id, command_id)
        REFERENCES flowpilot.task_commands (tenant_id, command_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS flowpilot.planned_actions (
    action_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    requester_id text NOT NULL,
    action_digest text NOT NULL,
    tool_name text NOT NULL,
    tool_schema_hash text NOT NULL,
    policy_version text NOT NULL,
    expires_at timestamptz NOT NULL,
    planned_action jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (
        tenant_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_version,
        expires_at
    ),
    UNIQUE (tenant_id, action_id),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES flowpilot.tasks (tenant_id, task_id),
    CHECK (planned_action ->> 'tenant_id' = tenant_id),
    CHECK (planned_action ->> 'task_id' = task_id),
    CHECK (planned_action ->> 'action_id' = action_id),
    CHECK (planned_action ->> 'requester_id' = requester_id),
    CHECK (planned_action ->> 'policy_version' = policy_version),
    CHECK ((planned_action ->> 'expires_at')::timestamptz = expires_at),
    CHECK (planned_action #>> '{tool,name}' = tool_name),
    CHECK (planned_action #>> '{tool,schema_hash}' = tool_schema_hash)
);

CREATE TABLE IF NOT EXISTS flowpilot.policy_decisions (
    policy_decision_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    action_digest text NOT NULL,
    policy_version text NOT NULL,
    expires_at timestamptz NOT NULL,
    policy_decision jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (
        tenant_id,
        policy_decision_id,
        action_digest,
        policy_version,
        expires_at
    ),
    UNIQUE (tenant_id, policy_decision_id),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES flowpilot.tasks (tenant_id, task_id),
    CHECK (policy_decision ->> 'policy_decision_id' = policy_decision_id),
    CHECK (policy_decision ->> 'tenant_id' = tenant_id),
    CHECK (policy_decision ->> 'task_id' = task_id),
    CHECK (policy_decision ->> 'action_digest' = action_digest),
    CHECK (policy_decision ->> 'policy_version' = policy_version),
    CHECK ((policy_decision ->> 'expires_at')::timestamptz = expires_at),
    CHECK (
        policy_decision #>> '{action,action_digest}' = action_digest
    )
);

CREATE TABLE IF NOT EXISTS flowpilot.approvals (
    approval_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    requester_id text NOT NULL,
    action_id text NOT NULL,
    action_digest text NOT NULL,
    tool_schema_hash text NOT NULL,
    policy_decision_id text NOT NULL,
    policy_version text NOT NULL,
    status text NOT NULL,
    approver_id text,
    decision_reason text,
    separation_of_duties_result boolean,
    requested_at timestamptz NOT NULL,
    decided_at timestamptz,
    expires_at timestamptz NOT NULL,
    approval jsonb NOT NULL,
    UNIQUE (tenant_id, approval_id),
    UNIQUE (
        tenant_id,
        approval_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_decision_id,
        policy_version,
        expires_at
    ),
    FOREIGN KEY (
        tenant_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_version,
        expires_at
    ) REFERENCES flowpilot.planned_actions (
        tenant_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_version,
        expires_at
    ),
    FOREIGN KEY (
        tenant_id,
        policy_decision_id,
        action_digest,
        policy_version,
        expires_at
    ) REFERENCES flowpilot.policy_decisions (
        tenant_id,
        policy_decision_id,
        action_digest,
        policy_version,
        expires_at
    ),
    CHECK (expires_at > requested_at),
    CHECK (decided_at IS NULL OR decided_at >= requested_at),
    CHECK (
        (status = 'pending'
            AND approver_id IS NULL
            AND decision_reason IS NULL
            AND separation_of_duties_result IS NULL
            AND decided_at IS NULL)
        OR
        (status = 'approved'
            AND approver_id IS NOT NULL
            AND approver_id <> requester_id
            AND separation_of_duties_result IS TRUE
            AND decided_at IS NOT NULL)
        OR
        (status = 'rejected'
            AND approver_id IS NOT NULL
            AND decision_reason IS NOT NULL
            AND separation_of_duties_result IS NOT NULL
            AND decided_at IS NOT NULL)
        OR
        (status IN ('expired', 'revoked') AND decided_at IS NOT NULL)
    ),
    CHECK (approval ->> 'approval_id' = approval_id),
    CHECK (approval ->> 'tenant_id' = tenant_id),
    CHECK (approval ->> 'action_id' = action_id),
    CHECK (approval ->> 'action_digest' = action_digest),
    CHECK (approval ->> 'tool_schema_hash' = tool_schema_hash),
    CHECK (approval ->> 'policy_decision_id' = policy_decision_id),
    CHECK (approval ->> 'policy_version' = policy_version),
    CHECK ((approval ->> 'expires_at')::timestamptz = expires_at)
);

CREATE TABLE IF NOT EXISTS flowpilot.tool_executions (
    tool_execution_id text PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    tool_name text NOT NULL,
    idempotency_key text NOT NULL,
    action_id text NOT NULL,
    action_digest text NOT NULL,
    planned_action jsonb NOT NULL,
    planned_action_expires_at timestamptz NOT NULL,
    policy_decision_id text NOT NULL,
    policy_version text NOT NULL,
    policy_decision jsonb NOT NULL,
    policy_expires_at timestamptz NOT NULL,
    tool_schema_hash text NOT NULL,
    approval_id text,
    approval jsonb,
    approval_expires_at timestamptz,
    intent jsonb NOT NULL,
    status text NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    outcome jsonb,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (tenant_id, tool_execution_id),
    UNIQUE (tenant_id, tool_name, idempotency_key),
    FOREIGN KEY (
        tenant_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_version,
        planned_action_expires_at
    ) REFERENCES flowpilot.planned_actions (
        tenant_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_version,
        expires_at
    ),
    FOREIGN KEY (
        tenant_id,
        policy_decision_id,
        action_digest,
        policy_version,
        policy_expires_at
    ) REFERENCES flowpilot.policy_decisions (
        tenant_id,
        policy_decision_id,
        action_digest,
        policy_version,
        expires_at
    ),
    FOREIGN KEY (
        tenant_id,
        approval_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_decision_id,
        policy_version,
        approval_expires_at
    ) REFERENCES flowpilot.approvals (
        tenant_id,
        approval_id,
        action_id,
        action_digest,
        tool_schema_hash,
        policy_decision_id,
        policy_version,
        expires_at
    ),
    CHECK (policy_expires_at = planned_action_expires_at),
    CHECK (
        policy_decision ->> 'decision' = 'allow'
        OR (
            policy_decision ->> 'decision' = 'require_approval'
            AND approval_id IS NOT NULL
        )
    ),
    CHECK (
        (approval_id IS NULL
            AND approval IS NULL
            AND approval_expires_at IS NULL)
        OR
        (approval_id IS NOT NULL
            AND approval IS NOT NULL
            AND approval_expires_at = planned_action_expires_at)
    ),
    CHECK (
        status IN (
            'prepared',
            'running',
            'succeeded',
            'verified',
            'failed_retryable',
            'failed_final',
            'unknown'
        )
    ),
    CHECK (
        (status IN ('prepared', 'running') AND outcome IS NULL)
        OR
        (status NOT IN ('prepared', 'running')
            AND outcome IS NOT NULL
            AND outcome ->> 'status' = status)
    ),
    CHECK (
        status <> 'unknown'
        OR (
            outcome -> 'retryable' = 'false'::jsonb
            AND outcome -> 'data' = 'null'::jsonb
            AND outcome -> 'retry_basis' = 'null'::jsonb
            AND outcome -> 'verification' = 'null'::jsonb
            AND jsonb_typeof(outcome -> 'error_code') = 'string'
            AND jsonb_typeof(outcome -> 'reconciliation') = 'object'
            AND outcome -> 'reconciliation' <> '{}'::jsonb
        )
    ),
    CHECK (
        status <> 'verified'
        OR (
            outcome -> 'retryable' = 'false'::jsonb
            AND jsonb_typeof(outcome -> 'data') = 'object'
            AND outcome -> 'data' <> '{}'::jsonb
            AND jsonb_typeof(outcome -> 'evidence_ref') = 'string'
            AND outcome #> '{verification,matched}' = 'true'::jsonb
            AND jsonb_typeof(
                outcome #> '{verification,observed_ref}'
            ) = 'string'
        )
    ),
    CHECK (
        status <> 'failed_retryable'
        OR (
            outcome -> 'retryable' = 'true'::jsonb
            AND outcome ->> 'retry_basis' IN (
                'not_sent',
                'confirmed_not_executed'
            )
            AND jsonb_typeof(outcome -> 'error_code') = 'string'
        )
    ),
    CHECK (
        status <> 'failed_final'
        OR (
            outcome -> 'retryable' = 'false'::jsonb
            AND outcome -> 'retry_basis' = 'null'::jsonb
            AND jsonb_typeof(outcome -> 'error_code') = 'string'
        )
    )
);

CREATE TABLE IF NOT EXISTS flowpilot.task_leases (
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    holder_id text NOT NULL,
    lease_token text NOT NULL UNIQUE,
    run_generation bigint NOT NULL CHECK (run_generation >= 1),
    acquired_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, task_id),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES flowpilot.tasks (tenant_id, task_id),
    CHECK (expires_at > acquired_at)
);

CREATE TABLE IF NOT EXISTS flowpilot.checkpoints (
    checkpoint_id text NOT NULL,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    thread_id text NOT NULL,
    run_generation bigint NOT NULL CHECK (run_generation >= 1),
    graph_version text NOT NULL,
    state jsonb NOT NULL,
    security_context_ref text NOT NULL,
    security_context_hash text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, thread_id, checkpoint_id),
    UNIQUE (tenant_id, task_id, checkpoint_id),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES flowpilot.tasks (tenant_id, task_id)
);

CREATE INDEX IF NOT EXISTS checkpoints_latest_idx
    ON flowpilot.checkpoints (
        tenant_id,
        thread_id,
        run_generation DESC,
        created_at DESC
    );

CREATE TABLE IF NOT EXISTS flowpilot.outbox_events (
    event_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence >= 1),
    event_type text NOT NULL,
    event jsonb NOT NULL,
    occurred_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
    published_at timestamptz,
    UNIQUE (tenant_id, event_id),
    UNIQUE (tenant_id, aggregate_type, aggregate_id, sequence),
    CHECK (event ->> 'event_id' = event_id),
    CHECK (event ->> 'tenant_id' = tenant_id),
    CHECK ((event ->> 'sequence')::bigint = sequence)
);

CREATE INDEX IF NOT EXISTS outbox_unpublished_idx
    ON flowpilot.outbox_events (tenant_id, available_at, occurred_at)
    WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS flowpilot.consumer_inbox (
    tenant_id text NOT NULL,
    consumer_id text NOT NULL,
    event_id text NOT NULL,
    payload_hash text NOT NULL,
    processed_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, consumer_id, event_id)
);

CREATE TABLE IF NOT EXISTS flowpilot.audit_streams (
    tenant_id text NOT NULL,
    stream_id text NOT NULL,
    next_sequence bigint NOT NULL DEFAULT 1 CHECK (next_sequence >= 1),
    head_hash text,
    PRIMARY KEY (tenant_id, stream_id),
    UNIQUE (stream_id)
);

CREATE TABLE IF NOT EXISTS flowpilot.audit_events (
    event_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    stream_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence >= 1),
    previous_hash text,
    event_hash text NOT NULL,
    event jsonb NOT NULL,
    occurred_at timestamptz NOT NULL,
    UNIQUE (tenant_id, stream_id, sequence),
    FOREIGN KEY (tenant_id, stream_id)
        REFERENCES flowpilot.audit_streams (tenant_id, stream_id),
    CHECK (event ->> 'event_id' = event_id),
    CHECK (event ->> 'tenant_id' = tenant_id),
    CHECK (event ->> 'stream_id' = stream_id),
    CHECK ((event ->> 'sequence')::bigint = sequence),
    CHECK (event #>> '{integrity,event_hash}' = event_hash),
    CHECK (
        (sequence = 1 AND previous_hash IS NULL)
        OR (sequence > 1 AND previous_hash IS NOT NULL)
    )
);

CREATE OR REPLACE FUNCTION flowpilot.enforce_command_update()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF ROW(
        OLD.command_id,
        OLD.tenant_id,
        OLD.task_id,
        OLD.command_type,
        OLD.expected_task_version,
        OLD.idempotency_key,
        OLD.command_digest,
        OLD.command,
        OLD.accepted_at
    ) IS DISTINCT FROM ROW(
        NEW.command_id,
        NEW.tenant_id,
        NEW.task_id,
        NEW.command_type,
        NEW.expected_task_version,
        NEW.idempotency_key,
        NEW.command_digest,
        NEW.command,
        NEW.accepted_at
    ) OR (
        OLD.execution_receipt IS NOT NULL
        AND OLD.execution_receipt IS DISTINCT FROM NEW.execution_receipt
    ) THEN
        RAISE EXCEPTION 'task command and receipt are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION flowpilot.enforce_approval_update()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF ROW(
        OLD.approval_id,
        OLD.tenant_id,
        OLD.task_id,
        OLD.requester_id,
        OLD.action_id,
        OLD.action_digest,
        OLD.tool_schema_hash,
        OLD.policy_decision_id,
        OLD.policy_version,
        OLD.requested_at,
        OLD.expires_at
    ) IS DISTINCT FROM ROW(
        NEW.approval_id,
        NEW.tenant_id,
        NEW.task_id,
        NEW.requester_id,
        NEW.action_id,
        NEW.action_digest,
        NEW.tool_schema_hash,
        NEW.policy_decision_id,
        NEW.policy_version,
        NEW.requested_at,
        NEW.expires_at
    ) OR OLD.status <> 'pending' OR NEW.status = 'pending' THEN
        RAISE EXCEPTION 'approval binding and terminal decision are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION flowpilot.enforce_execution_update()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    allowed boolean := false;
BEGIN
    IF ROW(
        OLD.tool_execution_id,
        OLD.request_id,
        OLD.tenant_id,
        OLD.task_id,
        OLD.tool_name,
        OLD.idempotency_key,
        OLD.action_id,
        OLD.action_digest,
        OLD.planned_action,
        OLD.planned_action_expires_at,
        OLD.policy_decision_id,
        OLD.policy_version,
        OLD.policy_decision,
        OLD.policy_expires_at,
        OLD.tool_schema_hash,
        OLD.approval_id,
        OLD.approval,
        OLD.approval_expires_at,
        OLD.intent,
        OLD.created_at
    ) IS DISTINCT FROM ROW(
        NEW.tool_execution_id,
        NEW.request_id,
        NEW.tenant_id,
        NEW.task_id,
        NEW.tool_name,
        NEW.idempotency_key,
        NEW.action_id,
        NEW.action_digest,
        NEW.planned_action,
        NEW.planned_action_expires_at,
        NEW.policy_decision_id,
        NEW.policy_version,
        NEW.policy_decision,
        NEW.policy_expires_at,
        NEW.tool_schema_hash,
        NEW.approval_id,
        NEW.approval,
        NEW.approval_expires_at,
        NEW.intent,
        NEW.created_at
    ) THEN
        RAISE EXCEPTION 'execution binding is immutable'
            USING ERRCODE = '55000';
    END IF;

    allowed := (
        (OLD.status = 'prepared' AND NEW.status = 'running')
        OR
        (OLD.status = 'running' AND NEW.status IN (
            'succeeded',
            'verified',
            'failed_retryable',
            'failed_final',
            'unknown'
        ))
        OR
        (OLD.status = 'succeeded' AND NEW.status IN (
            'verified',
            'failed_final',
            'unknown'
        ))
        OR
        (OLD.status = 'failed_retryable' AND NEW.status = 'running')
        OR
        (OLD.status = 'unknown' AND NEW.status IN (
            'verified',
            'failed_retryable',
            'failed_final'
        ))
    );
    IF NOT allowed THEN
        RAISE EXCEPTION 'invalid execution status transition % -> %',
            OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'unknown'
        AND NEW.status = 'failed_retryable'
        AND NEW.outcome ->> 'retry_basis' <> 'confirmed_not_executed' THEN
        RAISE EXCEPTION
            'unknown execution requires confirmed-not-executed evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS task_commands_update_guard
    ON flowpilot.task_commands;
CREATE TRIGGER task_commands_update_guard
BEFORE UPDATE ON flowpilot.task_commands
FOR EACH ROW EXECUTE FUNCTION flowpilot.enforce_command_update();

DROP TRIGGER IF EXISTS planned_actions_immutable
    ON flowpilot.planned_actions;
CREATE TRIGGER planned_actions_immutable
BEFORE UPDATE OR DELETE ON flowpilot.planned_actions
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_mutation();

DROP TRIGGER IF EXISTS policy_decisions_immutable
    ON flowpilot.policy_decisions;
CREATE TRIGGER policy_decisions_immutable
BEFORE UPDATE OR DELETE ON flowpilot.policy_decisions
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_mutation();

DROP TRIGGER IF EXISTS approvals_update_guard
    ON flowpilot.approvals;
CREATE TRIGGER approvals_update_guard
BEFORE UPDATE ON flowpilot.approvals
FOR EACH ROW EXECUTE FUNCTION flowpilot.enforce_approval_update();

DROP TRIGGER IF EXISTS approvals_no_delete
    ON flowpilot.approvals;
CREATE TRIGGER approvals_no_delete
BEFORE DELETE ON flowpilot.approvals
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_mutation();

DROP TRIGGER IF EXISTS tool_executions_update_guard
    ON flowpilot.tool_executions;
CREATE TRIGGER tool_executions_update_guard
BEFORE UPDATE ON flowpilot.tool_executions
FOR EACH ROW EXECUTE FUNCTION flowpilot.enforce_execution_update();

DROP TRIGGER IF EXISTS tool_executions_no_delete
    ON flowpilot.tool_executions;
CREATE TRIGGER tool_executions_no_delete
BEFORE DELETE ON flowpilot.tool_executions
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_mutation();

DROP TRIGGER IF EXISTS checkpoints_immutable
    ON flowpilot.checkpoints;
CREATE TRIGGER checkpoints_immutable
BEFORE UPDATE OR DELETE ON flowpilot.checkpoints
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_mutation();

DROP TRIGGER IF EXISTS audit_events_immutable
    ON flowpilot.audit_events;
CREATE TRIGGER audit_events_immutable
BEFORE UPDATE OR DELETE ON flowpilot.audit_events
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_mutation();

CREATE OR REPLACE FUNCTION flowpilot.append_audit_event(
    p_event_id text,
    p_tenant_id text,
    p_stream_id text,
    p_sequence bigint,
    p_previous_hash text,
    p_event_hash text,
    p_event jsonb,
    p_occurred_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, flowpilot
AS $function$
DECLARE
    stream flowpilot.audit_streams%ROWTYPE;
BEGIN
    IF p_tenant_id <> flowpilot.current_tenant_id() THEN
        RAISE EXCEPTION 'audit tenant does not match transaction tenant'
            USING ERRCODE = '42501';
    END IF;

    SELECT *
    INTO stream
    FROM flowpilot.audit_streams
    WHERE tenant_id = p_tenant_id AND stream_id = p_stream_id
    FOR UPDATE;

    IF NOT FOUND
        OR p_sequence <> stream.next_sequence
        OR p_previous_hash IS DISTINCT FROM stream.head_hash THEN
        RAISE EXCEPTION 'audit stream sequence or previous hash mismatch'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO flowpilot.audit_events (
        event_id,
        tenant_id,
        stream_id,
        sequence,
        previous_hash,
        event_hash,
        event,
        occurred_at
    )
    VALUES (
        p_event_id,
        p_tenant_id,
        p_stream_id,
        p_sequence,
        p_previous_hash,
        p_event_hash,
        p_event,
        p_occurred_at
    );

    UPDATE flowpilot.audit_streams
    SET next_sequence = next_sequence + 1,
        head_hash = p_event_hash
    WHERE tenant_id = p_tenant_id AND stream_id = p_stream_id;
END
$function$;

DO $rls$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'tasks',
        'task_commands',
        'task_command_slots',
        'planned_actions',
        'policy_decisions',
        'approvals',
        'tool_executions',
        'task_leases',
        'checkpoints',
        'outbox_events',
        'consumer_inbox',
        'audit_streams',
        'audit_events'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE flowpilot.%I ENABLE ROW LEVEL SECURITY',
            table_name
        );
        EXECUTE format(
            'ALTER TABLE flowpilot.%I FORCE ROW LEVEL SECURITY',
            table_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON flowpilot.%I',
            table_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON flowpilot.%I '
            'USING (tenant_id = flowpilot.current_tenant_id()) '
            'WITH CHECK (tenant_id = flowpilot.current_tenant_id())',
            table_name
        );
    END LOOP;
END
$rls$;

REVOKE ALL ON SCHEMA flowpilot FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA flowpilot FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA flowpilot FROM PUBLIC;

GRANT USAGE ON SCHEMA flowpilot
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway, flowpilot_publisher;
GRANT EXECUTE ON FUNCTION flowpilot.current_tenant_id()
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway, flowpilot_publisher;

GRANT SELECT ON flowpilot.tasks TO flowpilot_api, flowpilot_worker;
GRANT INSERT, SELECT, UPDATE ON flowpilot.task_commands TO flowpilot_api;
GRANT INSERT, SELECT ON flowpilot.task_command_slots TO flowpilot_api;

GRANT SELECT, INSERT, UPDATE ON flowpilot.tasks TO flowpilot_worker;
GRANT SELECT, INSERT, DELETE, UPDATE ON flowpilot.task_leases TO flowpilot_worker;
GRANT SELECT, INSERT ON flowpilot.checkpoints TO flowpilot_worker;
GRANT SELECT, INSERT, UPDATE ON flowpilot.outbox_events
    TO flowpilot_worker, flowpilot_gateway, flowpilot_publisher;
GRANT SELECT, INSERT ON flowpilot.consumer_inbox
    TO flowpilot_worker, flowpilot_gateway;

GRANT SELECT, INSERT ON flowpilot.planned_actions TO flowpilot_gateway;
GRANT SELECT, INSERT ON flowpilot.policy_decisions TO flowpilot_gateway;
GRANT SELECT, INSERT, UPDATE ON flowpilot.approvals TO flowpilot_gateway;
GRANT SELECT, INSERT, UPDATE ON flowpilot.tool_executions TO flowpilot_gateway;
GRANT SELECT ON flowpilot.audit_streams TO flowpilot_gateway;
GRANT SELECT ON flowpilot.audit_events TO flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.append_audit_event(
    text,
    text,
    text,
    bigint,
    text,
    text,
    jsonb,
    timestamptz
) TO flowpilot_gateway;

COMMIT;
