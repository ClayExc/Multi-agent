from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from flowpilot_domain import DataClassification
from flowpilot_persistence import PersistenceError, PersistenceErrorCode
from flowpilot_persistence.knowledge import PostgresKnowledgeContentProjections
from flowpilot_persistence.postgres import _TenantTransaction


class Connection:
    def __init__(self, row: Mapping[str, Any] | None) -> None:
        self.row = row
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []

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


def _row(excerpt: str = "safe excerpt") -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "document_id": "doc_12345678",
        "document_version": 3,
        "content_ref": "knowledge-content://safe",
        "content_hash": "sha256:" + "a" * 64,
        "data_classification": "internal",
        "content_excerpt": excerpt,
    }


def test_projection_is_exact_bounded_and_not_repr_visible() -> None:
    async def scenario() -> None:
        connection = Connection(_row())
        repository = PostgresKnowledgeContentProjections(_TenantTransaction(connection))
        projection = await repository.get_exact("tenant-a", "doc_12345678", 3)
        assert projection is not None
        assert projection.data_classification is DataClassification.INTERNAL
        assert projection.content_excerpt == "safe excerpt"
        assert "safe excerpt" not in repr(projection)

        sql, parameters = connection.statements[-1]
        assert "left(b.content_body,2048)" in sql
        assert sql.count("document_version=%(document_version)s") == 2
        assert sql.count("document_id=%(document_id)s") == 2
        assert sql.count("tenant_id=%(tenant_id)s") == 2
        assert "latest" not in sql.casefold()
        assert "d.lifecycle='active'" in sql
        assert "v.effective_at<=transaction_timestamp()" in sql
        assert "v.expires_at IS NULL" in sql
        assert parameters == {
            "tenant_id": "tenant-a",
            "document_id": "doc_12345678",
            "document_version": 3,
        }

    asyncio.run(scenario())


def test_missing_exact_projection_returns_none() -> None:
    async def scenario() -> None:
        repository = PostgresKnowledgeContentProjections(
            _TenantTransaction(Connection(None))
        )
        assert await repository.get_exact("tenant-a", "doc_12345678", 99) is None

    asyncio.run(scenario())


def test_projection_transaction_cannot_switch_tenant() -> None:
    async def scenario() -> None:
        repository = PostgresKnowledgeContentProjections(
            _TenantTransaction(Connection(None))
        )
        await repository.get_exact("tenant-a", "doc_12345678", 0)
        with pytest.raises(PersistenceError) as caught:
            await repository.get_exact("tenant-b", "doc_12345678", 0)
        assert caught.value.code is PersistenceErrorCode.TENANT_MISMATCH

    asyncio.run(scenario())


def test_malformed_or_oversized_driver_projection_fails_closed() -> None:
    async def scenario() -> None:
        repository = PostgresKnowledgeContentProjections(
            _TenantTransaction(Connection(_row("x" * 2049)))
        )
        with pytest.raises(ValueError):
            await repository.get_exact("tenant-a", "doc_12345678", 3)

    asyncio.run(scenario())
