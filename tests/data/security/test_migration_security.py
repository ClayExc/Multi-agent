from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "migrations" / "0001_persistence_baseline.sql"
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
