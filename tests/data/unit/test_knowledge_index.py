from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from flowpilot_domain import AclPrincipal, AclPrincipalType, DataClassification
from flowpilot_persistence.knowledge_index import (
    EMBEDDING_DIMENSION,
    HashEmbeddingAdapter,
    KnowledgeCandidateQuery,
    PostgresKnowledgeCandidateRepository,
    PostgresKnowledgeIndexer,
)
from flowpilot_persistence.postgres import _TenantTransaction


class Connection:
    def __init__(self, row: Mapping[str, Any] | None = None) -> None:
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []
        self.row = row

    async def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> int:
        self.statements.append((statement, parameters))
        return 1

    async def fetch_one(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        return self.row

    async def fetch_all(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        self.statements.append((statement, parameters))
        return ()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def test_hash_embedding_is_deterministic_versioned_and_normalized() -> None:
    async def scenario() -> None:
        adapter = HashEmbeddingAdapter()
        first = await adapter.embed("alpha beta alpha")
        second = await adapter.embed("alpha beta alpha")
        assert first == second
        assert len(first) == EMBEDDING_DIMENSION
        assert abs(sum(value * value for value in first) - 1.0) < 1e-12

    asyncio.run(scenario())


def test_candidate_sql_filters_authorization_before_returning_metadata() -> None:
    async def scenario() -> None:
        connection = Connection()
        repository = PostgresKnowledgeCandidateRepository(
            _TenantTransaction(connection)
        )
        query = KnowledgeCandidateQuery(
            tenant_id="tenant-a",
            purpose="support",
            principals=(AclPrincipal(AclPrincipalType.ROLE, "reader"),),
            classification_ceiling=DataClassification.INTERNAL,
            query_text="reset password",
            query_vector=(0.0,) * EMBEDDING_DIMENSION,
            observed_at=datetime(2026, 8, 16, tzinfo=UTC),
            limit=10,
        )
        assert await repository.candidates(query) == ()
        sql, parameters = connection.statements[-1]
        assert "d.lifecycle='active'" in sql
        assert "allowed_purposes" in sql and "principals" in sql
        assert "v.effective_at" in sql and "v.expires_at" in sql
        assert "data_classification" in sql
        assert "content_body" not in sql and "source_ref" not in sql
        assert parameters is not None and parameters["tenant_id"] == "tenant-a"
        assert parameters["principals"] == ["role:reader"]

    asyncio.run(scenario())


def test_query_rejects_wrong_vector_dimension() -> None:
    try:
        KnowledgeCandidateQuery(
            tenant_id="tenant-a",
            purpose="support",
            principals=(),
            classification_ceiling=DataClassification.PUBLIC,
            query_text="x",
            query_vector=(0.0,),
            observed_at=datetime(2026, 8, 16, tzinfo=UTC),
        )
    except ValueError as error:
        assert "dimension" in str(error)
    else:
        raise AssertionError("invalid vector dimension was accepted")


def test_pending_job_is_recovered_from_postgres_and_marked_ready() -> None:
    async def scenario() -> None:
        connection = Connection(
            {
                "job_id": "job_12345678",
                "document_id": "doc_12345678",
                "document_version": 0,
                "document_revision": 0,
                "content_hash": "sha256:" + "a" * 64,
                "operation": "upsert",
                "content_body": "reset password safely",
                "content_ref": "knowledge-content://safe",
            }
        )
        indexer = PostgresKnowledgeIndexer(_TenantTransaction(connection))
        assert await indexer.index_next("tenant-a", HashEmbeddingAdapter())
        sql = "\n".join(statement for statement, _ in connection.statements)
        assert "FOR UPDATE OF j SKIP LOCKED" in sql
        assert "knowledge_sections" in sql
        assert "index_state=%(state)s" in sql
        assert connection.statements[-1][1] is not None
        assert connection.statements[-1][1]["state"] == "ready"
        assert await indexer.mark_all_stale("tenant-a") == 1
        rebuild_sql = connection.statements[-1][0]
        assert "knowledge_index_jobs" in rebuild_sql
        assert "knowledge_documents" not in rebuild_sql

    asyncio.run(scenario())


def test_no_pending_postgres_job_is_stable_after_coordination_loss() -> None:
    async def scenario() -> None:
        connection = Connection()
        indexer = PostgresKnowledgeIndexer(_TenantTransaction(connection))
        assert not await indexer.index_next("tenant-a", HashEmbeddingAdapter())

    asyncio.run(scenario())
