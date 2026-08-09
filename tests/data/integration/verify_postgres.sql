\set ON_ERROR_STOP 1

BEGIN;

SET LOCAL ROLE flowpilot_api;
SELECT set_config('flowpilot.tenant_id', 'tenant-a', true);

DO $api_task_initialization$
BEGIN
    IF NOT has_table_privilege('flowpilot_api', 'flowpilot.tasks', 'INSERT') THEN
        RAISE EXCEPTION 'flowpilot_api lacks Task initialization permission';
    END IF;
    IF has_table_privilege('flowpilot_api', 'flowpilot.tasks', 'UPDATE')
       OR has_table_privilege('flowpilot_api', 'flowpilot.tasks', 'DELETE')
       OR has_table_privilege('flowpilot_api', 'flowpilot.tasks', 'TRUNCATE') THEN
        RAISE EXCEPTION 'flowpilot_api received non-minimal Task permission';
    END IF;
END
$api_task_initialization$;

INSERT INTO flowpilot.tasks (
    tenant_id,
    task_id,
    thread_id,
    status,
    version,
    run_generation,
    projection,
    created_at,
    updated_at
)
VALUES (
    'tenant-a',
    'task_api_init12345678',
    'thread_api_init12345678',
    'RECEIVED',
    0,
    0,
    '{
      "tenant_id": "tenant-a",
      "task_id": "task_api_init12345678",
      "version": 0,
      "run_generation": 0
    }'::jsonb,
    '2026-07-28T07:59:00Z',
    '2026-07-28T07:59:00Z'
);

SELECT set_config('flowpilot.tenant_id', 'tenant-b', true);

DO $api_cross_tenant$
BEGIN
    BEGIN
        INSERT INTO flowpilot.tasks (
            tenant_id,
            task_id,
            thread_id,
            status,
            version,
            run_generation,
            projection,
            created_at,
            updated_at
        )
        VALUES (
            'tenant-a',
            'task_api_attack12345678',
            'thread_api_attack12345678',
            'RECEIVED',
            0,
            0,
            '{
              "tenant_id": "tenant-a",
              "task_id": "task_api_attack12345678",
              "version": 0,
              "run_generation": 0
            }'::jsonb,
            '2026-07-28T07:59:00Z',
            '2026-07-28T07:59:00Z'
        );
        RAISE EXCEPTION 'flowpilot_api cross-tenant Task insert succeeded';
    EXCEPTION
        WHEN insufficient_privilege THEN
            NULL;
    END;
END
$api_cross_tenant$;

SET LOCAL ROLE flowpilot_worker;
SELECT set_config('flowpilot.tenant_id', 'tenant-a', true);

INSERT INTO flowpilot.tasks (
    tenant_id,
    task_id,
    thread_id,
    status,
    version,
    run_generation,
    projection,
    created_at,
    updated_at
)
VALUES (
    'tenant-a',
    'task_rls_a12345678',
    'thread_rls_a12345678',
    'RUNNABLE',
    1,
    0,
    $json${
      "task_id": "task_rls_a12345678",
      "thread_id": "thread_rls_a12345678",
      "tenant_id": "tenant-a",
      "status": "RUNNABLE",
      "version": 1,
      "run_generation": 0,
      "purpose": "it_support",
      "data_classification": "internal",
      "security_context": {
        "context_id": "secctx_rls_a12345678",
        "context_ref": "security-context://tenant-a/rls-a",
        "context_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "tenant_id": "tenant-a",
        "subject_id": "user-123",
        "subject_type": "user",
        "purpose": "it_support",
        "authentication": {
          "method": "oidc",
          "assurance_level": "substantial",
          "session_id_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        },
        "delegation_id": null,
        "data_classification_ceiling": "confidential",
        "issued_at": "2026-07-28T08:00:00Z",
        "expires_at": "2026-07-28T09:00:00Z"
      },
      "release": {
        "graph_version": "graph-v1",
        "domain_pack_version": "it-service-v1",
        "context_policy_version": "ctx-policy-v1",
        "policy_version": "policy-v1",
        "tool_schema_set": "tool-set-v1"
      },
      "waiting_on": null,
      "result_ref": null,
      "error": null,
      "created_at": "2026-07-28T08:00:00Z",
      "updated_at": "2026-07-28T08:00:00Z",
      "completed_at": null
    }$json$::jsonb,
    '2026-07-28T08:00:00Z',
    '2026-07-28T08:00:00Z'
);

SELECT set_config('flowpilot.tenant_id', 'tenant-b', true);

DO $test$
DECLARE
    visible_count bigint;
BEGIN
    SELECT count(*)
    INTO visible_count
    FROM flowpilot.tasks
    WHERE task_id = 'task_rls_a12345678';
    IF visible_count <> 0 THEN
        RAISE EXCEPTION 'cross-tenant read succeeded';
    END IF;

    BEGIN
        INSERT INTO flowpilot.tasks (
            tenant_id,
            task_id,
            thread_id,
            status,
            version,
            run_generation,
            projection,
            created_at,
            updated_at
        )
        VALUES (
            'tenant-a',
            'task_rls_attack1',
            'thread_rls_attack1',
            'RUNNABLE',
            1,
            0,
            $json${
              "task_id": "task_rls_attack1",
              "thread_id": "thread_rls_attack1",
              "tenant_id": "tenant-a",
              "status": "RUNNABLE",
              "version": 1,
              "run_generation": 0,
              "purpose": "it_support",
              "data_classification": "internal",
              "security_context": {
                "context_id": "secctx_rls_attack1",
                "context_ref": "security-context://tenant-a/rls-attack",
                "context_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "tenant_id": "tenant-a",
                "subject_id": "user-123",
                "subject_type": "user",
                "purpose": "it_support",
                "authentication": {
                  "method": "oidc",
                  "assurance_level": "substantial",
                  "session_id_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                },
                "delegation_id": null,
                "data_classification_ceiling": "confidential",
                "issued_at": "2026-07-28T08:00:00Z",
                "expires_at": "2026-07-28T09:00:00Z"
              },
              "release": {
                "graph_version": "graph-v1",
                "domain_pack_version": "it-service-v1",
                "context_policy_version": "ctx-policy-v1",
                "policy_version": "policy-v1",
                "tool_schema_set": "tool-set-v1"
              },
              "waiting_on": null,
              "result_ref": null,
              "error": null,
              "created_at": "2026-07-28T08:00:00Z",
              "updated_at": "2026-07-28T08:00:00Z",
              "completed_at": null
            }$json$::jsonb,
            '2026-07-28T08:00:00Z',
            '2026-07-28T08:00:00Z'
        );
        RAISE EXCEPTION 'cross-tenant write succeeded';
    EXCEPTION
        WHEN insufficient_privilege THEN
            NULL;
    END;
END
$test$;

INSERT INTO flowpilot.tasks (
    tenant_id,
    task_id,
    thread_id,
    status,
    version,
    run_generation,
    projection,
    created_at,
    updated_at
)
VALUES (
    'tenant-b',
    'task_rls_b12345678',
    'thread_rls_b12345678',
    'RUNNABLE',
    1,
    0,
    $json${
      "task_id": "task_rls_b12345678",
      "thread_id": "thread_rls_b12345678",
      "tenant_id": "tenant-b",
      "status": "RUNNABLE",
      "version": 1,
      "run_generation": 0,
      "purpose": "it_support",
      "data_classification": "internal",
      "security_context": {
        "context_id": "secctx_rls_b12345678",
        "context_ref": "security-context://tenant-b/rls-b",
        "context_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "tenant_id": "tenant-b",
        "subject_id": "user-456",
        "subject_type": "user",
        "purpose": "it_support",
        "authentication": {
          "method": "oidc",
          "assurance_level": "substantial",
          "session_id_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        },
        "delegation_id": null,
        "data_classification_ceiling": "confidential",
        "issued_at": "2026-07-28T08:00:00Z",
        "expires_at": "2026-07-28T09:00:00Z"
      },
      "release": {
        "graph_version": "graph-v1",
        "domain_pack_version": "it-service-v1",
        "context_policy_version": "ctx-policy-v1",
        "policy_version": "policy-v1",
        "tool_schema_set": "tool-set-v1"
      },
      "waiting_on": null,
      "result_ref": null,
      "error": null,
      "created_at": "2026-07-28T08:00:00Z",
      "updated_at": "2026-07-28T08:00:00Z",
      "completed_at": null
    }$json$::jsonb,
    '2026-07-28T08:00:00Z',
    '2026-07-28T08:00:00Z'
);

RESET ROLE;
SET LOCAL ROLE flowpilot_gateway;
SELECT set_config('flowpilot.tenant_id', 'tenant-a', true);

INSERT INTO flowpilot.planned_actions (
    action_id,
    tenant_id,
    task_id,
    requester_id,
    action_digest,
    tool_name,
    tool_schema_hash,
    policy_version,
    expires_at,
    planned_action,
    created_at
)
VALUES (
    'act_rls_12345678',
    'tenant-a',
    'task_rls_a12345678',
    'user-123',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'itsm.ticket.create.v1',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'policy-v1',
    '2026-07-28T09:00:00Z',
    '{"action_id":"act_rls_12345678","tenant_id":"tenant-a","task_id":"task_rls_a12345678","requester_id":"user-123","policy_version":"policy-v1","expires_at":"2026-07-28T09:00:00Z","tool":{"name":"itsm.ticket.create.v1","schema_hash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}'::jsonb,
    '2026-07-28T08:00:00Z'
);

INSERT INTO flowpilot.policy_decisions (
    policy_decision_id,
    tenant_id,
    task_id,
    action_digest,
    policy_version,
    expires_at,
    policy_decision,
    created_at
)
VALUES (
    'pd_rls_12345678',
    'tenant-a',
    'task_rls_a12345678',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'policy-v1',
    '2026-07-28T09:00:00Z',
    '{"decision_id":"pd_rls_12345678","tenant_id":"tenant-a","task_id":"task_rls_a12345678","action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","policy_version":"policy-v1","expires_at":"2026-07-28T09:00:00Z","decision":"require_approval","action":{"action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'::jsonb,
    '2026-07-28T08:00:00Z'
);

DO $test$
BEGIN
    BEGIN
        INSERT INTO flowpilot.approvals (
            approval_id,
            tenant_id,
            task_id,
            requester_id,
            action_id,
            action_digest,
            tool_schema_hash,
            policy_decision_id,
            policy_version,
            status,
            approver_id,
            decision_reason,
            separation_of_duties_result,
            requested_at,
            decided_at,
            expires_at,
            approval
        )
        VALUES (
            'apr_rls_12345678',
            'tenant-a',
            'task_rls_a12345678',
            'user-123',
            'act_rls_12345678',
            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
            'pd_rls_12345678',
            'policy-v1',
            'approved',
            'approver-456',
            NULL,
            true,
            '2026-07-28T08:00:00Z',
            '2026-07-28T08:30:00Z',
            '2026-07-28T09:01:00Z',
            '{"approval_id":"apr_rls_12345678","tenant_id":"tenant-a","action_id":"act_rls_12345678","action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","tool_schema_hash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","policy_decision_id":"pd_rls_12345678","policy_version":"policy-v1","expires_at":"2026-07-28T09:01:00Z"}'::jsonb
        );
        RAISE EXCEPTION 'approval expiry mismatch was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL;
    END;
END
$test$;

INSERT INTO flowpilot.approvals (
    approval_id,
    tenant_id,
    task_id,
    requester_id,
    action_id,
    action_digest,
    tool_schema_hash,
    policy_decision_id,
    policy_version,
    status,
    approver_id,
    decision_reason,
    separation_of_duties_result,
    requested_at,
    decided_at,
    expires_at,
    approval
)
VALUES (
    'apr_rls_87654321',
    'tenant-a',
    'task_rls_a12345678',
    'user-123',
    'act_rls_12345678',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'pd_rls_12345678',
    'policy-v1',
    'approved',
    'approver-456',
    NULL,
    true,
    '2026-07-28T08:00:00Z',
    '2026-07-28T08:30:00Z',
    '2026-07-28T09:00:00Z',
    '{"approval_id":"apr_rls_87654321","tenant_id":"tenant-a","action_id":"act_rls_12345678","action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","tool_schema_hash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","policy_decision_id":"pd_rls_12345678","policy_version":"policy-v1","expires_at":"2026-07-28T09:00:00Z"}'::jsonb
);

INSERT INTO flowpilot.tool_executions (
    tool_execution_id,
    request_id,
    tenant_id,
    task_id,
    tool_name,
    idempotency_key,
    action_id,
    action_digest,
    planned_action,
    planned_action_expires_at,
    policy_decision_id,
    policy_version,
    policy_decision,
    policy_expires_at,
    tool_schema_hash,
    approval_id,
    approval,
    approval_expires_at,
    intent,
    status,
    attempt_count,
    outcome,
    created_at,
    updated_at
)
VALUES (
    'tex_rls_12345678',
    'treq_rls_12345678',
    'tenant-a',
    'task_rls_a12345678',
    'itsm.ticket.create.v1',
    'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    'act_rls_12345678',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    '{"action_id":"act_rls_12345678","tenant_id":"tenant-a","task_id":"task_rls_a12345678","requester_id":"user-123","policy_version":"policy-v1","expires_at":"2026-07-28T09:00:00Z","tool":{"name":"itsm.ticket.create.v1","schema_hash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}'::jsonb,
    '2026-07-28T09:00:00Z',
    'pd_rls_12345678',
    'policy-v1',
    '{"decision_id":"pd_rls_12345678","tenant_id":"tenant-a","task_id":"task_rls_a12345678","action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","policy_version":"policy-v1","expires_at":"2026-07-28T09:00:00Z","decision":"require_approval","action":{"action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'::jsonb,
    '2026-07-28T09:00:00Z',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'apr_rls_87654321',
    '{"approval_id":"apr_rls_87654321","tenant_id":"tenant-a","action_id":"act_rls_12345678","action_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","tool_schema_hash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","policy_decision_id":"pd_rls_12345678","policy_version":"policy-v1","expires_at":"2026-07-28T09:00:00Z"}'::jsonb,
    '2026-07-28T09:00:00Z',
    '{"tool_execution_id":"tex_rls_12345678"}'::jsonb,
    'prepared',
    0,
    NULL,
    '2026-07-28T08:30:00Z',
    '2026-07-28T08:30:00Z'
);

UPDATE flowpilot.tool_executions
SET status = 'running',
    attempt_count = 1,
    updated_at = '2026-07-28T08:31:00Z'
WHERE tool_execution_id = 'tex_rls_12345678';

UPDATE flowpilot.tool_executions
SET status = 'unknown',
    outcome = '{
        "status":"unknown",
        "recorded_at":"2026-07-28T08:32:00Z",
        "retryable":false,
        "data":null,
        "error_code":"UPSTREAM_RESULT_UNKNOWN",
        "retry_basis":null,
        "evidence_ref":null,
        "verification":null,
        "reconciliation":{"status":"pending"}
    }'::jsonb,
    updated_at = '2026-07-28T08:32:00Z'
WHERE tool_execution_id = 'tex_rls_12345678';

DO $test$
BEGIN
    BEGIN
        UPDATE flowpilot.tool_executions
        SET status = 'running',
            outcome = NULL,
            updated_at = '2026-07-28T08:33:00Z'
        WHERE tool_execution_id = 'tex_rls_12345678';
        RAISE EXCEPTION 'unknown execution returned directly to running';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        UPDATE flowpilot.tool_executions
        SET status = 'failed_retryable',
            outcome = '{
                "status":"failed_retryable",
                "recorded_at":"2026-07-28T08:34:00Z",
                "retryable":true,
                "data":null,
                "error_code":"NETWORK_NOT_SENT",
                "retry_basis":"not_sent",
                "evidence_ref":null,
                "verification":null,
                "reconciliation":null
            }'::jsonb,
            updated_at = '2026-07-28T08:34:00Z'
        WHERE tool_execution_id = 'tex_rls_12345678';
        RAISE EXCEPTION 'unknown execution accepted not-sent retry proof';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END
$test$;

ROLLBACK;
