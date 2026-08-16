from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
UP = (ROOT / "migrations" / "0006_knowledge_document_facts.sql").read_text()
DOWN = (ROOT / "migrations" / "0006_knowledge_document_facts.down.sql").read_text()


def test_knowledge_migration_is_linear_atomic_and_rls_forced() -> None:
    assert UP.startswith("BEGIN;\n") and UP.rstrip().endswith("COMMIT;")
    assert "0005_governance_audit_query" in UP
    for table in (
        "knowledge_documents",
        "knowledge_document_versions",
        "knowledge_content_bodies",
        "knowledge_sections",
        "knowledge_inbox",
        "knowledge_outbox",
        "knowledge_index_jobs",
    ):
        assert table in UP
    assert "ENABLE ROW LEVEL SECURITY" in UP
    assert "FORCE ROW LEVEL SECURITY" in UP
    assert "current_tenant_id()" in UP


def test_versions_are_immutable_and_outbox_has_no_sensitive_columns() -> None:
    assert "knowledge versions are immutable" in UP
    outbox = UP[UP.index("CREATE TABLE IF NOT EXISTS flowpilot.knowledge_outbox") :]
    outbox = outbox[: outbox.index("CREATE TABLE IF NOT EXISTS", 1)]
    for forbidden in (
        "content_body",
        "source_ref",
        "principal_id",
        "context_ref",
        "token",
        "secret",
    ):
        assert forbidden not in outbox


def test_down_fails_before_destructive_ddl_when_facts_exist() -> None:
    assert DOWN.startswith("BEGIN;\n") and DOWN.rstrip().endswith("COMMIT;")
    assert DOWN.index("knowledge facts are not empty") < DOWN.index("DROP VIEW")
