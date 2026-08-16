from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
UP = (ROOT / "migrations" / "0007_pgvector_knowledge_index.sql").read_text()
DOWN = (ROOT / "migrations" / "0007_pgvector_knowledge_index.down.sql").read_text()
COMPOSE = (ROOT / "infra" / "compose" / "compose.yaml").read_text()


def test_pgvector_migration_is_linear_versioned_and_reversible() -> None:
    assert UP.startswith("BEGIN;\n") and UP.rstrip().endswith("COMMIT;")
    assert "0007 requires 0006" in UP
    assert "flowpilot.vector(384)" in UP
    assert "embedding_model" in UP and "embedding_version" in UP
    assert "knowledge_sections_keyword_idx" in UP
    assert "knowledge_sections_embedding_idx" in UP
    assert DOWN.index("knowledge index is not empty") < DOWN.index("DROP INDEX")


def test_compose_uses_pgvector_and_mounts_linear_heads_read_only() -> None:
    assert "pgvector/pgvector:0.8.0-pg17" in COMPOSE
    assert "006-knowledge-document-facts.sql:ro" in COMPOSE
    assert "007-pgvector-knowledge-index.sql:ro" in COMPOSE
