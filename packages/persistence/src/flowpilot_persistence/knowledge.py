from __future__ import annotations

# ruff: noqa: E501
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from flowpilot_application import (
    KnowledgeContentProjection,
    KnowledgeDiagnostic,
    KnowledgeIdempotencyClaim,
    KnowledgeIdempotencyDisposition,
    KnowledgeIndexJob,
    KnowledgeIndexState,
    KnowledgeOperation,
    KnowledgeOperationDisposition,
    KnowledgeOperationReceipt,
    KnowledgeOutboxEvent,
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
    KnowledgeLifecycle,
    KnowledgeSource,
    KnowledgeSourceType,
)
from flowpilot_security import TrustedSecurityContext

from .postgres import (
    AsyncPostgresConnection,
    AsyncPostgresConnectionFactory,
    _TenantTransaction,
)

Row = Mapping[str, Any]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_object(value: object) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("stored knowledge JSON is not an object")
    return parsed


def _document(row: Row) -> KnowledgeDocument:
    return KnowledgeDocument(
        tenant_id=str(row["tenant_id"]),
        document_id=str(row["document_id"]),
        revision=int(row["revision"]),
        current_version=int(row["current_version"]),
        lifecycle=KnowledgeLifecycle(str(row["lifecycle"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retired_at=row.get("retired_at"),
        deleted_at=row.get("deleted_at"),
    )


def _version(row: Row) -> DocumentVersion:
    acl = _json_object(row["acl"])
    principals = tuple(
        AclPrincipal(
            AclPrincipalType(str(item["principal_type"])), str(item["principal_id"])
        )
        for item in acl.get("principals", [])
        if isinstance(item, dict)
    )
    source = KnowledgeSource(
        source_type=KnowledgeSourceType(str(row["source_type"])),
        source_ref=str(row["source_ref"]),
        source_version=row.get("source_version"),
        source_digest=str(row["source_digest"]),
    )
    return DocumentVersion(
        tenant_id=str(row["tenant_id"]),
        document_id=str(row["document_id"]),
        version=int(row["document_version"]),
        source=source,
        access_control=KnowledgeAccessControl(
            principals=principals,
            allowed_purposes=tuple(
                str(item) for item in acl.get("allowed_purposes", [])
            ),
            tenant_wide=acl.get("tenant_wide", False),
        ),
        data_classification=DataClassification(str(row["data_classification"])),
        effective_at=row["effective_at"],
        expires_at=row.get("expires_at"),
        content_ref=str(row["content_ref"]),
        content_hash=str(row["content_hash"]),
        created_at=row["created_at"],
    )


_DOCUMENT_COLUMNS = """tenant_id,document_id,revision,current_version,lifecycle,
created_at,updated_at,retired_at,deleted_at"""
_VERSION_COLUMNS = """tenant_id,document_id,document_version,source_type,source_ref,
source_version,source_digest,acl,data_classification,effective_at,expires_at,
content_ref,content_hash,created_at"""


class PostgresKnowledgeRepository:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def get_document(
        self, tenant_id: str, document_id: str, *, for_update: bool = False
    ) -> KnowledgeDocument | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            f"SELECT {_DOCUMENT_COLUMNS} FROM flowpilot.knowledge_documents "
            "WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s"
            + (" FOR UPDATE" if for_update else ""),
            {"tenant_id": tenant_id, "document_id": document_id},
        )
        return None if row is None else _document(row)

    async def get_version(
        self, tenant_id: str, document_id: str, document_version: int
    ) -> DocumentVersion | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            f"SELECT {_VERSION_COLUMNS} FROM flowpilot.knowledge_document_versions "
            "WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s "
            "AND document_version=%(document_version)s",
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "document_version": document_version,
            },
        )
        return None if row is None else _version(row)

    @staticmethod
    def _document_parameters(document: KnowledgeDocument) -> dict[str, object]:
        return {
            "tenant_id": document.tenant_id,
            "document_id": document.document_id,
            "revision": document.revision,
            "current_version": document.current_version,
            "lifecycle": document.lifecycle.value,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "retired_at": document.retired_at,
            "deleted_at": document.deleted_at,
        }

    @staticmethod
    def _version_parameters(
        version: DocumentVersion, content: KnowledgeContent
    ) -> dict[str, object]:
        return {
            "tenant_id": version.tenant_id,
            "document_id": version.document_id,
            "document_version": version.version,
            "source_type": version.source.source_type.value,
            "source_ref": version.source.source_ref,
            "source_version": version.source.source_version,
            "source_digest": version.source.source_digest,
            "acl": _json(version.access_control.to_mapping()),
            "data_classification": version.data_classification.value,
            "effective_at": version.effective_at,
            "expires_at": version.expires_at,
            "content_ref": version.content_ref,
            "content_hash": version.content_hash,
            "created_at": version.created_at,
            "content": content.text,
        }

    async def add(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion,
        content: KnowledgeContent,
    ) -> KnowledgeRepositoryDisposition:
        await self._transaction.bind(document.tenant_id)
        if (document.revision, document.current_version, version.version) != (
            0,
            0,
            0,
        ) or version.content_hash != content.content_hash:
            return KnowledgeRepositoryDisposition.CONFLICT
        affected = await self._transaction.connection.execute(
            """INSERT INTO flowpilot.knowledge_documents
               (tenant_id,document_id,revision,current_version,lifecycle,created_at,updated_at,retired_at,deleted_at)
               VALUES (%(tenant_id)s,%(document_id)s,%(revision)s,%(current_version)s,%(lifecycle)s,
                       %(created_at)s,%(updated_at)s,%(retired_at)s,%(deleted_at)s)
               ON CONFLICT DO NOTHING""",
            self._document_parameters(document),
        )
        if affected != 1:
            return KnowledgeRepositoryDisposition.CONFLICT
        await self._insert_version(version, content)
        return KnowledgeRepositoryDisposition.APPLIED

    async def _insert_version(
        self, version: DocumentVersion, content: KnowledgeContent
    ) -> None:
        params = self._version_parameters(version, content)
        await self._transaction.connection.execute(
            """INSERT INTO flowpilot.knowledge_document_versions
               (tenant_id,document_id,document_version,source_type,source_ref,source_version,
                source_digest,acl,data_classification,effective_at,expires_at,content_ref,content_hash,created_at)
               VALUES (%(tenant_id)s,%(document_id)s,%(document_version)s,%(source_type)s,%(source_ref)s,
                       %(source_version)s,%(source_digest)s,%(acl)s::jsonb,%(data_classification)s,
                       %(effective_at)s,%(expires_at)s,%(content_ref)s,%(content_hash)s,%(created_at)s)""",
            params,
        )
        await self._transaction.connection.execute(
            """INSERT INTO flowpilot.knowledge_content_bodies
               (tenant_id,document_id,document_version,content_hash,content_body)
               VALUES (%(tenant_id)s,%(document_id)s,%(document_version)s,%(content_hash)s,%(content)s)""",
            params,
        )

    async def update(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion,
        content: KnowledgeContent,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition:
        await self._transaction.bind(document.tenant_id)
        if (
            document.revision != expected_revision + 1
            or version.version != document.current_version
            or version.content_hash != content.content_hash
        ):
            return KnowledgeRepositoryDisposition.CONFLICT
        affected = await self._transaction.connection.execute(
            """UPDATE flowpilot.knowledge_documents SET revision=%(revision)s,
               current_version=%(current_version)s,lifecycle=%(lifecycle)s,updated_at=%(updated_at)s
               WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s
                 AND revision=%(expected_revision)s AND lifecycle='active'""",
            {
                **self._document_parameters(document),
                "expected_revision": expected_revision,
            },
        )
        if affected != 1:
            return KnowledgeRepositoryDisposition.CONFLICT
        await self._insert_version(version, content)
        return KnowledgeRepositoryDisposition.APPLIED

    async def retire(
        self, document: KnowledgeDocument, *, expected_revision: int
    ) -> KnowledgeRepositoryDisposition:
        return await self._lifecycle(document, expected_revision, erase=False)

    async def delete(
        self, document: KnowledgeDocument, *, expected_revision: int
    ) -> KnowledgeRepositoryDisposition:
        return await self._lifecycle(document, expected_revision, erase=True)

    async def _lifecycle(
        self, document: KnowledgeDocument, expected_revision: int, *, erase: bool
    ) -> KnowledgeRepositoryDisposition:
        await self._transaction.bind(document.tenant_id)
        affected = await self._transaction.connection.execute(
            """UPDATE flowpilot.knowledge_documents SET revision=%(revision)s,lifecycle=%(lifecycle)s,
               updated_at=%(updated_at)s,retired_at=%(retired_at)s,deleted_at=%(deleted_at)s
               WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s AND revision=%(expected_revision)s
                 AND lifecycle<>'deleted'""",
            {
                **self._document_parameters(document),
                "expected_revision": expected_revision,
            },
        )
        if affected != 1:
            return KnowledgeRepositoryDisposition.CONFLICT
        if erase:
            await self._transaction.connection.execute(
                "DELETE FROM flowpilot.knowledge_content_bodies WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s",
                {"tenant_id": document.tenant_id, "document_id": document.document_id},
            )
            await self._transaction.connection.execute(
                "DELETE FROM flowpilot.knowledge_sections WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s",
                {"tenant_id": document.tenant_id, "document_id": document.document_id},
            )
        return KnowledgeRepositoryDisposition.APPLIED


class PostgresKnowledgeInbox:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def claim(
        self, tenant_id: str, idempotency_key: str, request_digest: str
    ) -> KnowledgeIdempotencyClaim:
        await self._transaction.bind(tenant_id)
        inserted = await self._transaction.connection.execute(
            """INSERT INTO flowpilot.knowledge_inbox(tenant_id,idempotency_key,request_digest)
               VALUES (%(tenant_id)s,%(key)s,%(digest)s) ON CONFLICT DO NOTHING""",
            {"tenant_id": tenant_id, "key": idempotency_key, "digest": request_digest},
        )
        if inserted == 1:
            return KnowledgeIdempotencyClaim(KnowledgeIdempotencyDisposition.CLAIMED)
        row = await self._transaction.connection.fetch_one(
            "SELECT request_digest,receipt FROM flowpilot.knowledge_inbox WHERE tenant_id=%(tenant_id)s AND idempotency_key=%(key)s FOR UPDATE",
            {"tenant_id": tenant_id, "key": idempotency_key},
        )
        if (
            row is None
            or row["request_digest"] != request_digest
            or row.get("receipt") is None
        ):
            return KnowledgeIdempotencyClaim(KnowledgeIdempotencyDisposition.CONFLICT)
        data = _json_object(row["receipt"])
        receipt = KnowledgeOperationReceipt(
            tenant_id=str(data["tenant_id"]),
            document_id=str(data["document_id"]),
            operation=KnowledgeOperation(str(data["operation"])),
            revision=int(data["revision"]),
            document_version=int(data["document_version"]),
            disposition=KnowledgeOperationDisposition(str(data["disposition"])),
            event_id=str(data["event_id"]),
            index_job_id=str(data["index_job_id"]),
        )
        return KnowledgeIdempotencyClaim(
            KnowledgeIdempotencyDisposition.DUPLICATE, receipt
        )

    async def complete(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_digest: str,
        receipt: KnowledgeOperationReceipt,
    ) -> None:
        await self._transaction.bind(tenant_id)
        payload = {
            "tenant_id": receipt.tenant_id,
            "document_id": receipt.document_id,
            "operation": receipt.operation.value,
            "revision": receipt.revision,
            "document_version": receipt.document_version,
            "disposition": receipt.disposition.value,
            "event_id": receipt.event_id,
            "index_job_id": receipt.index_job_id,
        }
        affected = await self._transaction.connection.execute(
            """UPDATE flowpilot.knowledge_inbox SET receipt=%(receipt)s::jsonb,completed_at=transaction_timestamp()
               WHERE tenant_id=%(tenant_id)s AND idempotency_key=%(key)s AND request_digest=%(digest)s AND receipt IS NULL""",
            {
                "tenant_id": tenant_id,
                "key": idempotency_key,
                "digest": request_digest,
                "receipt": _json(payload),
            },
        )
        if affected != 1:
            raise RuntimeError("knowledge inbox completion conflicted")


class PostgresKnowledgeOutbox:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def add(self, event: KnowledgeOutboxEvent) -> None:
        await self._transaction.bind(event.tenant_id)
        await self._transaction.connection.execute(
            """INSERT INTO flowpilot.knowledge_outbox
               (tenant_id,event_id,event_type,document_id,document_version,document_revision,payload,occurred_at)
               VALUES (%(tenant_id)s,%(event_id)s,%(event_type)s,%(document_id)s,%(document_version)s,
                       %(document_revision)s,%(payload)s::jsonb,%(occurred_at)s)""",
            {
                "tenant_id": event.tenant_id,
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "document_id": event.document_id,
                "document_version": event.document_version,
                "document_revision": event.document_revision,
                "payload": _json(event.safe_payload()),
                "occurred_at": event.occurred_at,
            },
        )


class PostgresKnowledgeIndexJobs:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def enqueue(self, job: KnowledgeIndexJob) -> bool:
        await self._transaction.bind(job.tenant_id)
        affected = await self._transaction.connection.execute(
            """INSERT INTO flowpilot.knowledge_index_jobs
               (tenant_id,job_id,document_id,document_version,document_revision,content_hash,operation,requested_at)
               VALUES (%(tenant_id)s,%(job_id)s,%(document_id)s,%(document_version)s,%(document_revision)s,
                       %(content_hash)s,%(operation)s,%(requested_at)s) ON CONFLICT DO NOTHING""",
            job.__dict__
            if hasattr(job, "__dict__")
            else {
                "tenant_id": job.tenant_id,
                "job_id": job.job_id,
                "document_id": job.document_id,
                "document_version": job.document_version,
                "document_revision": job.document_revision,
                "content_hash": job.content_hash,
                "operation": job.operation.value,
                "requested_at": job.requested_at,
            },
        )
        if affected == 1:
            return True
        row = await self._transaction.connection.fetch_one(
            """SELECT document_id,document_version,document_revision,content_hash,
                      operation,requested_at
               FROM flowpilot.knowledge_index_jobs
               WHERE tenant_id=%(tenant_id)s AND job_id=%(job_id)s""",
            {"tenant_id": job.tenant_id, "job_id": job.job_id},
        )
        expected = {
            "document_id": job.document_id,
            "document_version": job.document_version,
            "document_revision": job.document_revision,
            "content_hash": job.content_hash,
            "operation": job.operation.value,
            "requested_at": job.requested_at,
        }
        if row is None or any(row.get(key) != value for key, value in expected.items()):
            raise RuntimeError("knowledge index job identity conflicted")
        return False

    async def diagnostic(
        self, tenant_id: str, document_id: str, document_version: int
    ) -> KnowledgeDiagnostic | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """SELECT tenant_id,document_id,document_version,document_revision,content_hash,
                      index_state,last_job_id,indexed_at,failure_code
               FROM flowpilot.knowledge_index_diagnostics WHERE tenant_id=%(tenant_id)s
                 AND document_id=%(document_id)s AND document_version=%(document_version)s""",
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "document_version": document_version,
            },
        )
        if row is None:
            return None
        return KnowledgeDiagnostic(
            tenant_id=str(row["tenant_id"]),
            document_id=str(row["document_id"]),
            document_version=int(row["document_version"]),
            document_revision=int(row["document_revision"]),
            content_hash=str(row["content_hash"]),
            index_state=KnowledgeIndexState(str(row["index_state"])),
            last_job_id=row.get("last_job_id"),
            indexed_at=row.get("indexed_at"),
            failure_code=row.get("failure_code"),
        )


class PostgresKnowledgeContentProjections:
    """Exact-version excerpt projection, evaluated only inside a bound Query UoW."""

    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def get_exact(
        self,
        tenant_id: str,
        document_id: str,
        document_version: int,
    ) -> KnowledgeContentProjection | None:
        await self._transaction.bind(tenant_id)
        row = await self._transaction.connection.fetch_one(
            """SELECT b.tenant_id,b.document_id,b.document_version,
                      v.content_ref,v.content_hash,v.data_classification,
                      left(b.content_body,2048) AS content_excerpt
               FROM flowpilot.knowledge_content_bodies b
               JOIN flowpilot.knowledge_document_versions v
                 ON (v.tenant_id,v.document_id,v.document_version)=
                    (b.tenant_id,b.document_id,b.document_version)
               JOIN flowpilot.knowledge_documents d
                 ON (d.tenant_id,d.document_id)=(b.tenant_id,b.document_id)
               WHERE b.tenant_id=%(tenant_id)s
                 AND b.document_id=%(document_id)s
                 AND b.document_version=%(document_version)s
                 AND v.tenant_id=%(tenant_id)s
                 AND v.document_id=%(document_id)s
                 AND v.document_version=%(document_version)s
                 AND b.content_hash=v.content_hash
                 AND d.lifecycle='active'
                 AND v.effective_at<=transaction_timestamp()
                 AND (v.expires_at IS NULL OR v.expires_at>transaction_timestamp())""",
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "document_version": document_version,
            },
        )
        if row is None:
            return None
        return KnowledgeContentProjection(
            tenant_id=str(row["tenant_id"]),
            document_id=str(row["document_id"]),
            document_version=int(row["document_version"]),
            content_ref=str(row["content_ref"]),
            content_hash=str(row["content_hash"]),
            data_classification=DataClassification(str(row["data_classification"])),
            content_excerpt=str(row["content_excerpt"]),
        )


class PostgresKnowledgeUnitOfWork:
    def __init__(
        self,
        factory: AsyncPostgresConnectionFactory,
        trusted_context: TrustedSecurityContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory, self._trusted = factory, trusted_context
        self._clock = clock or (lambda: datetime.now(UTC))
        self._connection: AsyncPostgresConnection | None = None
        self._transaction: _TenantTransaction | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        connection = await self._factory()
        self._connection = connection
        transaction = _TenantTransaction(connection, self._trusted)
        self._transaction = transaction
        try:
            await transaction.activate(self._clock())
        except BaseException:
            await connection.rollback()
            await connection.close()
            self._connection = None
            raise
        self.documents = PostgresKnowledgeRepository(transaction)
        self.inbox = PostgresKnowledgeInbox(transaction)
        self.outbox = PostgresKnowledgeOutbox(transaction)
        self.index_jobs = PostgresKnowledgeIndexJobs(transaction)
        self.content_projections = PostgresKnowledgeContentProjections(transaction)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if self._connection is None:
            return
        try:
            if exc_type is not None or not self._committed:
                await self._connection.rollback()
            await self._connection.execute("RESET ALL")
            await self._connection.commit()
        finally:
            await self._connection.close()
            self._connection = None
            self._transaction = None

    async def commit(self) -> None:
        if self._connection is None or self._committed:
            raise RuntimeError("knowledge unit of work is not active")
        await self._connection.commit()
        self._committed = True
        if self._transaction is not None:
            self._transaction.finish()


class PostgresKnowledgeUnitOfWorkFactory:
    def __init__(
        self,
        connection_factory: AsyncPostgresConnectionFactory,
        trusted_context: TrustedSecurityContext,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory, self._trusted = connection_factory, trusted_context
        self._clock = clock

    def __call__(self) -> PostgresKnowledgeUnitOfWork:
        return PostgresKnowledgeUnitOfWork(self._factory, self._trusted, self._clock)
