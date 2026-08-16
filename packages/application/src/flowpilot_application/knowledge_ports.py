from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from flowpilot_domain import (
    DocumentVersion,
    KnowledgeContent,
    KnowledgeDocument,
)

from .knowledge_models import (
    KnowledgeAuthorizationDecision,
    KnowledgeAuthorizationRequest,
    KnowledgeDiagnostic,
    KnowledgeIdempotencyClaim,
    KnowledgeIndexJob,
    KnowledgeOperationReceipt,
    KnowledgeOutboxEvent,
    KnowledgeRepositoryDisposition,
)


class KnowledgeAuthorizationPort(Protocol):
    """Trusted policy boundary; decisions must bind the exact safe request digest."""

    async def authorize(
        self,
        request: KnowledgeAuthorizationRequest,
    ) -> KnowledgeAuthorizationDecision: ...


class KnowledgeContentSafetyPort(Protocol):
    """Central DLP/prompt-safety boundary; implementations must not retain text."""

    def assert_safe(self, content: str) -> None: ...


class KnowledgeRepositoryPort(Protocol):
    """Tenant-bound document facts and immutable versions.

    Mutation methods are compare-and-swap operations. ``delete`` must tombstone
    the aggregate and erase all stored content bodies in the same transaction,
    while retaining only safe version metadata needed to reject stale citations.
    """

    async def get_document(
        self,
        tenant_id: str,
        document_id: str,
        *,
        for_update: bool = False,
    ) -> KnowledgeDocument | None: ...

    async def get_version(
        self,
        tenant_id: str,
        document_id: str,
        document_version: int,
    ) -> DocumentVersion | None: ...

    async def add(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion,
        content: KnowledgeContent,
    ) -> KnowledgeRepositoryDisposition: ...

    async def update(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion,
        content: KnowledgeContent,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition: ...

    async def retire(
        self,
        document: KnowledgeDocument,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition: ...

    async def delete(
        self,
        document: KnowledgeDocument,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition: ...


class KnowledgeOperationInboxPort(Protocol):
    """Transactional idempotency claim completed in the same UoW as facts."""

    async def claim(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> KnowledgeIdempotencyClaim: ...

    async def complete(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_digest: str,
        receipt: KnowledgeOperationReceipt,
    ) -> None: ...


class KnowledgeOutboxPort(Protocol):
    """Append a metadata-only event in the document transaction."""

    async def add(self, event: KnowledgeOutboxEvent) -> None: ...


class KnowledgeIndexJobPort(Protocol):
    """Transactional index queue and safe diagnostic projection."""

    async def enqueue(self, job: KnowledgeIndexJob) -> bool:
        """Return True once and False only for an identical existing job."""

    async def diagnostic(
        self,
        tenant_id: str,
        document_id: str,
        document_version: int,
    ) -> KnowledgeDiagnostic | None: ...


class KnowledgeUnitOfWork(Protocol):
    """One DB transaction for document, inbox, outbox, and index job writes."""

    @property
    def documents(self) -> KnowledgeRepositoryPort: ...

    @property
    def inbox(self) -> KnowledgeOperationInboxPort: ...

    @property
    def outbox(self) -> KnowledgeOutboxPort: ...

    @property
    def index_jobs(self) -> KnowledgeIndexJobPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class KnowledgeUnitOfWorkFactory(Protocol):
    def __call__(self) -> KnowledgeUnitOfWork: ...


class KnowledgeQueryUnitOfWork(Protocol):
    """Tenant-bound read transaction for exact-version and diagnostic queries."""

    @property
    def documents(self) -> KnowledgeRepositoryPort: ...

    @property
    def index_jobs(self) -> KnowledgeIndexJobPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class KnowledgeQueryUnitOfWorkFactory(Protocol):
    def __call__(self) -> KnowledgeQueryUnitOfWork: ...
