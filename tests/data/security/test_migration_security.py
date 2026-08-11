from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "migrations" / "0001_persistence_baseline.sql"
).read_text(encoding="utf-8")
CHECKPOINT_MIGRATION = (
    ROOT / "migrations" / "0002_checkpoint_sequence_cas.sql"
).read_text(encoding="utf-8")
CHECKPOINT_DOWN = (
    ROOT / "migrations" / "0002_checkpoint_sequence_cas.down.sql"
).read_text(encoding="utf-8")
TASK_INITIALIZATION_MIGRATION = (
    ROOT / "migrations" / "0003_api_task_initialization.sql"
).read_text(encoding="utf-8")
TASK_INITIALIZATION_DOWN = (
    ROOT / "migrations" / "0003_api_task_initialization.down.sql"
).read_text(encoding="utf-8")
SECURITY_CONTEXT_MIGRATION = (
    ROOT / "migrations" / "0004_security_context_rls_binding.sql"
).read_text(encoding="utf-8")
SECURITY_CONTEXT_DOWN = (
    ROOT / "migrations" / "0004_security_context_rls_binding.down.sql"
).read_text(encoding="utf-8")

TENANT_TABLES = {
    "tasks",
    "task_commands",
    "task_command_slots",
    "planned_actions",
    "policy_decisions",
    "approvals",
    "tool_executions",
    "task_leases",
    "checkpoints",
    "outbox_events",
    "consumer_inbox",
    "audit_streams",
    "audit_events",
}


def test_migration_is_atomic_and_bound_to_contract_digest() -> None:
    assert MIGRATION.startswith("BEGIN;\n")
    assert MIGRATION.rstrip().endswith("COMMIT;")
    assert (
        "sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc"
        in MIGRATION
    )
    assert "migration id is bound to another content digest" in MIGRATION


def test_every_tenant_table_is_forced_through_rls() -> None:
    for table in TENANT_TABLES:
        assert f"'{table}'" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "tenant_id = flowpilot.current_tenant_id()" in MIGRATION
    assert MIGRATION.count("NOBYPASSRLS") == 4


def test_approval_policy_and_action_expiry_are_database_bound() -> None:
    assert "policy_expires_at = planned_action_expires_at" in MIGRATION
    assert "approval_expires_at = planned_action_expires_at" in MIGRATION
    assert "policy_decision ->> 'decision' = 'require_approval'" in MIGRATION
    assert "REFERENCES flowpilot.planned_actions" in MIGRATION
    assert "REFERENCES flowpilot.policy_decisions" in MIGRATION
    assert "REFERENCES flowpilot.approvals" in MIGRATION
    assert "execution binding is immutable" in MIGRATION
    assert "approval binding and terminal decision are immutable" in MIGRATION


def test_unknown_cannot_blindly_transition_to_running() -> None:
    unknown_block = MIGRATION.split(
        "(OLD.status = 'unknown' AND NEW.status IN (", maxsplit=1
    )[1].split("))", maxsplit=1)[0]
    assert "'running'" not in unknown_block
    assert "'failed_retryable'" in unknown_block
    assert "'verified'" in unknown_block


def test_append_only_audit_uses_locked_chain_head() -> None:
    assert "FOR UPDATE;" in MIGRATION
    assert "audit stream sequence or previous hash mismatch" in MIGRATION
    assert "audit_events_immutable" in MIGRATION
    assert "SECURITY DEFINER" in MIGRATION


def test_real_database_verification_covers_rls_and_expiry_negative_cases() -> None:
    script = (
        ROOT / "tests" / "data" / "integration" / "verify_postgres.sql"
    ).read_text(encoding="utf-8")
    assert "cross-tenant read succeeded" in script
    assert "cross-tenant write succeeded" in script
    assert "approval expiry mismatch was accepted" in script
    assert "unknown execution returned directly to running" in script
    assert "unknown execution accepted not-sent retry proof" in script
    assert "WHEN foreign_key_violation" in script
    assert "flowpilot_api received non-minimal Task permission" in script
    assert "flowpilot_api cross-tenant Task insert succeeded" in script


def test_checkpoint_migration_is_linear_atomic_and_repeatable() -> None:
    assert CHECKPOINT_MIGRATION.startswith("BEGIN;\n")
    assert CHECKPOINT_MIGRATION.rstrip().endswith("COMMIT;")
    assert "requires 0001_persistence_baseline" in CHECKPOINT_MIGRATION
    assert "0002_checkpoint_sequence_cas" in CHECKPOINT_MIGRATION
    assert "ADD COLUMN IF NOT EXISTS checkpoint_sequence bigint" in (
        CHECKPOINT_MIGRATION
    )
    assert "checkpoints_task_sequence_key" in CHECKPOINT_MIGRATION
    assert "checkpoints_task_thread_fk" in CHECKPOINT_MIGRATION
    assert "checkpoint_sequence DESC" in CHECKPOINT_MIGRATION


def test_checkpoint_down_fails_before_lossy_thread_rollback() -> None:
    assert CHECKPOINT_DOWN.startswith("BEGIN;\n")
    assert CHECKPOINT_DOWN.rstrip().endswith("COMMIT;")
    guard = CHECKPOINT_DOWN.index(
        "cannot restore tenant/thread uniqueness while duplicate tasks exist"
    )
    destructive_change = CHECKPOINT_DOWN.index(
        "DROP COLUMN IF EXISTS checkpoint_sequence"
    )
    assert guard < destructive_change


def test_task_initialization_migration_is_linear_atomic_and_minimal() -> None:
    assert TASK_INITIALIZATION_MIGRATION.startswith("BEGIN;\n")
    assert TASK_INITIALIZATION_MIGRATION.rstrip().endswith("COMMIT;")
    assert "requires 0002_checkpoint_sequence_cas" in (
        TASK_INITIALIZATION_MIGRATION
    )
    assert (
        "sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2"
        in TASK_INITIALIZATION_MIGRATION
    )
    assert "GRANT INSERT ON flowpilot.tasks TO flowpilot_api" in (
        TASK_INITIALIZATION_MIGRATION
    )
    for forbidden in ("UPDATE", "DELETE", "TRUNCATE"):
        assert f"GRANT {forbidden} ON flowpilot.tasks TO flowpilot_api" not in (
            TASK_INITIALIZATION_MIGRATION
        )


def test_task_initialization_down_revokes_before_migration_record() -> None:
    assert TASK_INITIALIZATION_DOWN.startswith("BEGIN;\n")
    assert TASK_INITIALIZATION_DOWN.rstrip().endswith("COMMIT;")
    revoke = TASK_INITIALIZATION_DOWN.index(
        "REVOKE INSERT ON flowpilot.tasks FROM flowpilot_api"
    )
    delete_record = TASK_INITIALIZATION_DOWN.index(
        "DELETE FROM flowpilot.schema_migrations"
    )
    assert revoke < delete_record
    successor_guard = CHECKPOINT_DOWN.index(
        "rollback 0003_api_task_initialization before 0002_checkpoint_sequence_cas"
    )
    destructive_change = CHECKPOINT_DOWN.index(
        "DROP COLUMN IF EXISTS checkpoint_sequence"
    )
    assert successor_guard < destructive_change


def test_security_context_migration_is_linear_atomic_and_role_safe() -> None:
    assert SECURITY_CONTEXT_MIGRATION.startswith("BEGIN;\n")
    assert SECURITY_CONTEXT_MIGRATION.rstrip().endswith("COMMIT;")
    assert "requires 0003_api_task_initialization" in SECURITY_CONTEXT_MIGRATION
    for role in (
        "flowpilot_api",
        "flowpilot_worker",
        "flowpilot_gateway",
        "flowpilot_publisher",
    ):
        assert f"ALTER ROLE {role} NOLOGIN NOSUPERUSER" in (
            SECURITY_CONTEXT_MIGRATION
        )
    for unsafe_flag in ("rolsuper", "rolbypassrls", "rolcanlogin", "rolinherit"):
        assert unsafe_flag in SECURITY_CONTEXT_MIGRATION
    assert "tenant runtime database roles are unsafe" in SECURITY_CONTEXT_MIGRATION


def test_security_context_store_is_revocable_rls_fact_source() -> None:
    for field in (
        "context_ref text PRIMARY KEY",
        "context_id text NOT NULL UNIQUE",
        "tenant_id text NOT NULL",
        "context_hash text NOT NULL",
        "subject_id text NOT NULL",
        "expires_at timestamptz NOT NULL",
        "context_snapshot jsonb NOT NULL",
        "identity_token_hash text NOT NULL",
        "active boolean NOT NULL DEFAULT true",
        "revoked_at timestamptz",
    ):
        assert field in SECURITY_CONTEXT_MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in SECURITY_CONTEXT_MIGRATION
    assert "CREATE POLICY security_context_binding" in SECURITY_CONTEXT_MIGRATION
    assert "flowpilot.validate_security_context()" in SECURITY_CONTEXT_MIGRATION
    assert "security context snapshots are immutable" in SECURITY_CONTEXT_MIGRATION
    assert "security contexts cannot be deleted" in SECURITY_CONTEXT_MIGRATION


def test_security_context_down_guards_data_and_predecessor_order() -> None:
    guard = SECURITY_CONTEXT_DOWN.index(
        "cannot drop non-empty security context store"
    )
    destructive = SECURITY_CONTEXT_DOWN.index(
        "DROP TABLE flowpilot.security_contexts"
    )
    assert guard < destructive
    successor = TASK_INITIALIZATION_DOWN.index(
        "rollback 0004_security_context_rls_binding before 0003_api_task_initialization"
    )
    revoke = TASK_INITIALIZATION_DOWN.index(
        "REVOKE INSERT ON flowpilot.tasks FROM flowpilot_api"
    )
    assert successor < revoke


def test_persistence_does_not_import_graph_package() -> None:
    source_root = (
        ROOT / "packages" / "persistence" / "src" / "flowpilot_persistence"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(source_root.glob("*.py"))
    )
    assert "flowpilot_graph" not in source
