from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from flowpilot_application import (
    KnowledgeIdempotencyDisposition,
    KnowledgeRepositoryDisposition,
)
from flowpilot_domain import (
    AclPrincipal,
    AclPrincipalType,
    DataClassification,
    DocumentVersion,
    KnowledgeAccessControl,
    KnowledgeContent,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeSourceType,
)
from flowpilot_persistence.knowledge import (
    PostgresKnowledgeInbox,
    PostgresKnowledgeRepository,
)
from flowpilot_persistence.postgres import _TenantTransaction


class Connection:
    def __init__(self, results: list[int] | None = None) -> None:
        self.results = results or []
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []

    async def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> int:
        self.statements.append((statement, parameters))
        return self.results.pop(0) if self.results else 1

    async def fetch_one(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        return None

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


def _facts() -> tuple[KnowledgeDocument, DocumentVersion, KnowledgeContent]:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    content = KnowledgeContent.from_text("safe knowledge")
    version = DocumentVersion(
        tenant_id="tenant-a",
        document_id="doc_12345678",
        version=0,
        source=KnowledgeSource.build(
            source_type=KnowledgeSourceType.MANUAL, source_ref="internal://one"
        ),
        access_control=KnowledgeAccessControl(
            principals=(AclPrincipal(AclPrincipalType.ROLE, "reader"),),
            allowed_purposes=("support",),
        ),
        data_classification=DataClassification.INTERNAL,
        effective_at=now,
        expires_at=None,
        content_ref="knowledge-content://safe",
        content_hash=content.content_hash,
        created_at=now,
    )
    return KnowledgeDocument.start(version), version, content


def test_repository_import_is_one_tenant_bound_fact_and_body_write() -> None:
    async def scenario() -> None:
        connection = Connection()
        repository = PostgresKnowledgeRepository(_TenantTransaction(connection))
        document, version, content = _facts()
        assert (
            await repository.add(document, version, content)
            is KnowledgeRepositoryDisposition.APPLIED
        )
        sql = "\n".join(statement for statement, _ in connection.statements)
        assert sql.count("set_config('flowpilot.tenant_id'") == 1
        assert "knowledge_documents" in sql
        assert "knowledge_document_versions" in sql
        assert "knowledge_content_bodies" in sql

    asyncio.run(scenario())


def test_repository_conflict_writes_no_version_or_body() -> None:
    async def scenario() -> None:
        connection = Connection([1, 0])
        repository = PostgresKnowledgeRepository(_TenantTransaction(connection))
        document, version, content = _facts()
        assert (
            await repository.add(document, version, content)
            is KnowledgeRepositoryDisposition.CONFLICT
        )
        sql = "\n".join(statement for statement, _ in connection.statements)
        assert "knowledge_document_versions" not in sql
        assert "knowledge_content_bodies" not in sql

    asyncio.run(scenario())


def test_inbox_new_claim_is_atomic_and_digest_bound() -> None:
    async def scenario() -> None:
        connection = Connection()
        inbox = PostgresKnowledgeInbox(_TenantTransaction(connection))
        result = await inbox.claim("tenant-a", "idem_12345678", "sha256:" + "a" * 64)
        assert result.disposition is KnowledgeIdempotencyDisposition.CLAIMED
        assert "ON CONFLICT DO NOTHING" in connection.statements[-1][0]

    asyncio.run(scenario())


def test_delete_erases_bodies_after_successful_cas() -> None:
    async def scenario() -> None:
        connection = Connection()
        repository = PostgresKnowledgeRepository(_TenantTransaction(connection))
        document, _, _ = _facts()
        deleted = document.delete(expected_revision=0, now=document.updated_at)
        assert (
            await repository.delete(deleted, expected_revision=0)
            is KnowledgeRepositoryDisposition.APPLIED
        )
        assert (
            "DELETE FROM flowpilot.knowledge_content_bodies"
            in connection.statements[-2][0]
        )
        assert (
            "DELETE FROM flowpilot.knowledge_sections" in connection.statements[-1][0]
        )

    asyncio.run(scenario())
