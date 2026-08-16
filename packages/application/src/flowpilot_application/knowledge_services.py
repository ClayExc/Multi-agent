from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from flowpilot_domain import (
    DataClassification,
    DocumentVersion,
    DomainErrorCode,
    DomainViolation,
    KnowledgeAccessControl,
    KnowledgeDocument,
    KnowledgeLifecycle,
    StableCitation,
)

from .errors import ApplicationError, ErrorCode
from .knowledge_models import (
    KnowledgeAuthorizationDecision,
    KnowledgeAuthorizationRequest,
    KnowledgeCitationResolution,
    KnowledgeDiagnostic,
    KnowledgeDocumentProjection,
    KnowledgeEventType,
    KnowledgeIdempotencyClaim,
    KnowledgeIdempotencyDisposition,
    KnowledgeImportRequest,
    KnowledgeIndexJob,
    KnowledgeIndexOperation,
    KnowledgeLifecycleRequest,
    KnowledgeOperation,
    KnowledgeOperationDisposition,
    KnowledgeOperationReceipt,
    KnowledgeOutboxEvent,
    KnowledgeReadRequest,
    KnowledgeRebuildRequest,
    KnowledgeRepositoryDisposition,
    KnowledgeRequestContext,
    KnowledgeUpdateRequest,
    classification_allows,
)
from .knowledge_ports import (
    KnowledgeAuthorizationPort,
    KnowledgeContentSafetyPort,
    KnowledgeQueryUnitOfWorkFactory,
    KnowledgeUnitOfWork,
    KnowledgeUnitOfWorkFactory,
)

Clock = Callable[[], datetime]


class KnowledgeCommandService:
    """Lifecycle command service with one transactional persistence boundary."""

    def __init__(
        self,
        *,
        unit_of_work: KnowledgeUnitOfWorkFactory,
        authorization: KnowledgeAuthorizationPort,
        content_safety: KnowledgeContentSafetyPort,
        clock: Clock | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._authorization = authorization
        self._content_safety = content_safety
        self._clock = clock or (lambda: datetime.now(UTC))

    async def import_document(
        self,
        request: KnowledgeImportRequest,
    ) -> KnowledgeOperationReceipt:
        now = self._now()
        self._assert_context(request.context, now)
        self._assert_request_digest(request.request_digest, request.recompute_digest())
        self._assert_content_safe(request.content.text)
        decision = await self._authorize(
            context=request.context,
            operation=KnowledgeOperation.IMPORT,
            document_id=request.document_id,
            target_classification=request.data_classification,
            target_content_hash=request.content.content_hash,
            current_revision=None,
            current_acl=None,
            target_acl=request.access_control,
            now=now,
        )
        version = DocumentVersion(
            tenant_id=request.context.tenant_id,
            document_id=request.document_id,
            version=0,
            source=request.source,
            access_control=request.access_control,
            data_classification=request.data_classification,
            effective_at=request.effective_at,
            expires_at=request.expires_at,
            content_ref=_content_ref(
                request.context.tenant_id,
                request.document_id,
                0,
                request.content.content_hash,
            ),
            content_hash=request.content.content_hash,
            created_at=now,
        )
        document = KnowledgeDocument.start(version)
        try:
            async with self._unit_of_work() as unit_of_work:
                duplicate = await self._claim(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    KnowledgeOperation.IMPORT,
                    request.idempotency_key,
                    request.request_digest,
                )
                if duplicate is not None:
                    return duplicate
                disposition = await unit_of_work.documents.add(
                    document,
                    version,
                    request.content,
                )
                if disposition is KnowledgeRepositoryDisposition.CONFLICT:
                    raise ApplicationError(
                        ErrorCode.KNOWLEDGE_ALREADY_EXISTS,
                        "knowledge document already exists",
                    )
                self._assert_repository_applied(disposition)
                return await self._finish(
                    unit_of_work,
                    operation=KnowledgeOperation.IMPORT,
                    event_type=KnowledgeEventType.IMPORTED,
                    index_operation=KnowledgeIndexOperation.UPSERT,
                    document=document,
                    version=version,
                    decision=decision,
                    idempotency_key=request.idempotency_key,
                    request_digest=request.request_digest,
                    now=now,
                )
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def update_document(
        self,
        request: KnowledgeUpdateRequest,
    ) -> KnowledgeOperationReceipt:
        now = self._now()
        self._assert_context(request.context, now)
        self._assert_request_digest(request.request_digest, request.recompute_digest())
        self._assert_content_safe(request.content.text)
        try:
            async with self._unit_of_work() as unit_of_work:
                document, current = await self._load_current(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    for_update=True,
                )
                decision = await self._authorize(
                    context=request.context,
                    operation=KnowledgeOperation.UPDATE,
                    document_id=request.document_id,
                    target_classification=request.data_classification,
                    target_content_hash=request.content.content_hash,
                    current_revision=document.revision,
                    current_acl=current.access_control,
                    target_acl=request.access_control,
                    now=now,
                )
                duplicate = await self._claim(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    KnowledgeOperation.UPDATE,
                    request.idempotency_key,
                    request.request_digest,
                )
                if duplicate is not None:
                    return duplicate
                next_number = document.current_version + 1
                version = DocumentVersion(
                    tenant_id=document.tenant_id,
                    document_id=document.document_id,
                    version=next_number,
                    source=request.source,
                    access_control=request.access_control,
                    data_classification=request.data_classification,
                    effective_at=request.effective_at,
                    expires_at=request.expires_at,
                    content_ref=_content_ref(
                        document.tenant_id,
                        document.document_id,
                        next_number,
                        request.content.content_hash,
                    ),
                    content_hash=request.content.content_hash,
                    created_at=now,
                )
                updated = document.advance(
                    version,
                    expected_revision=request.expected_revision,
                    now=now,
                )
                disposition = await unit_of_work.documents.update(
                    updated,
                    version,
                    request.content,
                    expected_revision=request.expected_revision,
                )
                if disposition is KnowledgeRepositoryDisposition.CONFLICT:
                    raise _version_conflict()
                self._assert_repository_applied(disposition)
                return await self._finish(
                    unit_of_work,
                    operation=KnowledgeOperation.UPDATE,
                    event_type=KnowledgeEventType.UPDATED,
                    index_operation=KnowledgeIndexOperation.UPSERT,
                    document=updated,
                    version=version,
                    decision=decision,
                    idempotency_key=request.idempotency_key,
                    request_digest=request.request_digest,
                    now=now,
                )
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def retire_document(
        self,
        request: KnowledgeLifecycleRequest,
    ) -> KnowledgeOperationReceipt:
        return await self._transition_document(
            request,
            operation=KnowledgeOperation.RETIRE,
            event_type=KnowledgeEventType.RETIRED,
        )

    async def delete_document(
        self,
        request: KnowledgeLifecycleRequest,
    ) -> KnowledgeOperationReceipt:
        return await self._transition_document(
            request,
            operation=KnowledgeOperation.DELETE,
            event_type=KnowledgeEventType.DELETED,
        )

    async def rebuild_document(
        self,
        request: KnowledgeRebuildRequest,
    ) -> KnowledgeOperationReceipt:
        now = self._now()
        self._assert_context(request.context, now)
        self._assert_request_digest(request.request_digest, request.recompute_digest())
        try:
            async with self._unit_of_work() as unit_of_work:
                document, version = await self._load_current(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    for_update=True,
                )
                if document.lifecycle is not KnowledgeLifecycle.ACTIVE:
                    raise _lifecycle_conflict()
                if (
                    document.revision != request.expected_revision
                    or document.current_version != request.document_version
                ):
                    raise _version_conflict()
                decision = await self._authorize(
                    context=request.context,
                    operation=KnowledgeOperation.REBUILD,
                    document_id=request.document_id,
                    target_classification=version.data_classification,
                    target_content_hash=version.content_hash,
                    current_revision=document.revision,
                    current_acl=version.access_control,
                    target_acl=version.access_control,
                    now=now,
                )
                duplicate = await self._claim(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    KnowledgeOperation.REBUILD,
                    request.idempotency_key,
                    request.request_digest,
                )
                if duplicate is not None:
                    return duplicate
                return await self._finish(
                    unit_of_work,
                    operation=KnowledgeOperation.REBUILD,
                    event_type=KnowledgeEventType.REBUILD_REQUESTED,
                    index_operation=KnowledgeIndexOperation.REBUILD,
                    document=document,
                    version=version,
                    decision=decision,
                    idempotency_key=request.idempotency_key,
                    request_digest=request.request_digest,
                    now=now,
                )
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def _transition_document(
        self,
        request: KnowledgeLifecycleRequest,
        *,
        operation: KnowledgeOperation,
        event_type: KnowledgeEventType,
    ) -> KnowledgeOperationReceipt:
        now = self._now()
        self._assert_context(request.context, now)
        self._assert_request_digest(
            request.request_digest,
            request.recompute_digest(operation),
        )
        try:
            async with self._unit_of_work() as unit_of_work:
                document, version = await self._load_current(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    for_update=True,
                )
                decision = await self._authorize(
                    context=request.context,
                    operation=operation,
                    document_id=request.document_id,
                    target_classification=version.data_classification,
                    target_content_hash=version.content_hash,
                    current_revision=document.revision,
                    current_acl=version.access_control,
                    target_acl=version.access_control,
                    now=now,
                )
                duplicate = await self._claim(
                    unit_of_work,
                    request.context.tenant_id,
                    request.document_id,
                    operation,
                    request.idempotency_key,
                    request.request_digest,
                )
                if duplicate is not None:
                    return duplicate
                if operation is KnowledgeOperation.RETIRE:
                    updated = document.retire(
                        expected_revision=request.expected_revision,
                        now=now,
                    )
                    disposition = await unit_of_work.documents.retire(
                        updated,
                        expected_revision=request.expected_revision,
                    )
                else:
                    updated = document.delete(
                        expected_revision=request.expected_revision,
                        now=now,
                    )
                    disposition = await unit_of_work.documents.delete(
                        updated,
                        expected_revision=request.expected_revision,
                    )
                if disposition is KnowledgeRepositoryDisposition.CONFLICT:
                    raise _version_conflict()
                self._assert_repository_applied(disposition)
                return await self._finish(
                    unit_of_work,
                    operation=operation,
                    event_type=event_type,
                    index_operation=KnowledgeIndexOperation.REMOVE,
                    document=updated,
                    version=version,
                    decision=decision,
                    idempotency_key=request.idempotency_key,
                    request_digest=request.request_digest,
                    now=now,
                )
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def _finish(
        self,
        unit_of_work: KnowledgeUnitOfWork,
        *,
        operation: KnowledgeOperation,
        event_type: KnowledgeEventType,
        index_operation: KnowledgeIndexOperation,
        document: KnowledgeDocument,
        version: DocumentVersion,
        decision: KnowledgeAuthorizationDecision,
        idempotency_key: str,
        request_digest: str,
        now: datetime,
    ) -> KnowledgeOperationReceipt:
        identity_seed = f"{idempotency_key}\x00{request_digest}"
        suffix = hashlib.sha256(identity_seed.encode()).hexdigest()[:32]
        event_id = f"kevt_{suffix}"
        job_id = f"kjob_{suffix}"
        job = KnowledgeIndexJob(
            job_id=job_id,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            document_version=version.version,
            document_revision=document.revision,
            content_hash=version.content_hash,
            operation=index_operation,
            requested_at=now,
        )
        event = KnowledgeOutboxEvent(
            event_id=event_id,
            event_type=event_type,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            document_version=version.version,
            document_revision=document.revision,
            content_hash=version.content_hash,
            data_classification=version.data_classification,
            acl_digest=version.access_control.digest(),
            policy_decision_id=decision.decision_id,
            policy_version=decision.policy_version,
            occurred_at=now,
        )
        if not await unit_of_work.index_jobs.enqueue(job):
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
                "knowledge index queue returned a conflicting job",
            )
        await unit_of_work.outbox.add(event)
        receipt = KnowledgeOperationReceipt(
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            operation=operation,
            revision=document.revision,
            document_version=version.version,
            disposition=KnowledgeOperationDisposition.APPLIED,
            event_id=event_id,
            index_job_id=job_id,
        )
        await unit_of_work.inbox.complete(
            document.tenant_id,
            idempotency_key,
            request_digest,
            receipt,
        )
        await unit_of_work.commit()
        return receipt

    async def _claim(
        self,
        unit_of_work: KnowledgeUnitOfWork,
        tenant_id: str,
        document_id: str,
        operation: KnowledgeOperation,
        idempotency_key: str,
        request_digest: str,
    ) -> KnowledgeOperationReceipt | None:
        claim = await unit_of_work.inbox.claim(
            tenant_id,
            idempotency_key,
            request_digest,
        )
        if not isinstance(claim, KnowledgeIdempotencyClaim):
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
                "knowledge inbox returned an invalid claim",
            )
        if claim.disposition is KnowledgeIdempotencyDisposition.CONFLICT:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_IDEMPOTENCY_CONFLICT,
                "idempotency key is bound to another knowledge operation",
            )
        if claim.disposition is KnowledgeIdempotencyDisposition.CLAIMED:
            return None
        receipt = claim.receipt
        if (
            receipt is None
            or receipt.tenant_id != tenant_id
            or receipt.document_id != document_id
            or receipt.operation is not operation
        ):
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
                "knowledge inbox returned a mismatched receipt",
            )
        return replace(receipt, disposition=KnowledgeOperationDisposition.DUPLICATE)

    async def _load_current(
        self,
        unit_of_work: KnowledgeUnitOfWork,
        tenant_id: str,
        document_id: str,
        *,
        for_update: bool,
    ) -> tuple[KnowledgeDocument, DocumentVersion]:
        document = await unit_of_work.documents.get_document(
            tenant_id,
            document_id,
            for_update=for_update,
        )
        if document is None:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_NOT_FOUND,
                "knowledge document was not found",
            )
        _assert_document_binding(document, tenant_id, document_id)
        version = await unit_of_work.documents.get_version(
            tenant_id,
            document_id,
            document.current_version,
        )
        if version is None:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
                "knowledge repository omitted the current document version",
            )
        _assert_version_binding(version, document, document.current_version)
        return document, version

    def _assert_content_safe(self, content: str) -> None:
        try:
            self._content_safety.assert_safe(content)
        except Exception:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_CONTENT_UNSAFE,
                "knowledge content failed centralized safety validation",
            ) from None

    async def _authorize(
        self,
        *,
        context: KnowledgeRequestContext,
        operation: KnowledgeOperation,
        document_id: str,
        target_classification: DataClassification,
        target_content_hash: str,
        current_revision: int | None,
        current_acl: KnowledgeAccessControl | None,
        target_acl: KnowledgeAccessControl,
        now: datetime,
    ) -> KnowledgeAuthorizationDecision:
        return await _authorize_exact(
            self._authorization,
            context=context,
            operation=operation,
            document_id=document_id,
            target_classification=target_classification,
            target_content_hash=target_content_hash,
            current_revision=current_revision,
            current_acl=current_acl,
            target_acl=target_acl,
            now=now,
        )

    @staticmethod
    def _assert_context(context: KnowledgeRequestContext, now: datetime) -> None:
        trusted = context.security_context
        if context.tenant_id != trusted.tenant_id:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_TENANT_MISMATCH,
                "knowledge tenant does not match the trusted context",
            )
        if context.purpose != trusted.purpose:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_PURPOSE_DENIED,
                "knowledge purpose does not match the trusted context",
            )
        if now < trusted.issued_at or now >= trusted.expires_at:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_AUTHORIZATION_DENIED,
                "trusted knowledge context is not active",
            )

    @staticmethod
    def _assert_request_digest(provided: str, computed: str) -> None:
        if provided != computed:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_CONTRACT_INVALID,
                "knowledge request digest does not match request metadata",
            )

    @staticmethod
    def _assert_repository_applied(
        disposition: KnowledgeRepositoryDisposition,
    ) -> None:
        if disposition is not KnowledgeRepositoryDisposition.APPLIED:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
                "knowledge repository returned an invalid disposition",
            )

    def _now(self) -> datetime:
        observed = self._clock()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("knowledge service clock must be timezone-aware")
        return observed.astimezone(UTC)


class KnowledgeQueryService:
    """Exact-version metadata, citation, and index diagnostic reads."""

    def __init__(
        self,
        *,
        unit_of_work: KnowledgeQueryUnitOfWorkFactory,
        authorization: KnowledgeAuthorizationPort,
        clock: Clock | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._authorization = authorization
        self._clock = clock or (lambda: datetime.now(UTC))

    async def get_document(
        self,
        request: KnowledgeReadRequest,
    ) -> KnowledgeDocumentProjection:
        now = self._now()
        KnowledgeCommandService._assert_context(request.context, now)
        try:
            async with self._unit_of_work() as unit_of_work:
                document = await unit_of_work.documents.get_document(
                    request.context.tenant_id,
                    request.document_id,
                )
                if document is None:
                    raise _not_found()
                _assert_document_binding(
                    document,
                    request.context.tenant_id,
                    request.document_id,
                )
                version_number = (
                    document.current_version
                    if request.document_version is None
                    else request.document_version
                )
                version = await unit_of_work.documents.get_version(
                    request.context.tenant_id,
                    request.document_id,
                    version_number,
                )
                if version is None:
                    raise _not_found()
                _assert_version_binding(version, document, version_number)
                self._assert_available(document, version, now)
                await self._authorize_read(
                    request.context,
                    KnowledgeOperation.QUERY,
                    document,
                    version,
                    now,
                )
                return KnowledgeDocumentProjection(document=document, version=version)
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def resolve_citation(
        self,
        context: KnowledgeRequestContext,
        citation: StableCitation,
    ) -> KnowledgeCitationResolution:
        now = self._now()
        KnowledgeCommandService._assert_context(context, now)
        if citation.tenant_id != context.tenant_id:
            raise ApplicationError(
                ErrorCode.KNOWLEDGE_TENANT_MISMATCH,
                "citation tenant does not match the trusted context",
            )
        try:
            async with self._unit_of_work() as unit_of_work:
                document = await unit_of_work.documents.get_document(
                    context.tenant_id,
                    citation.document_id,
                )
                if document is None:
                    raise _reference_unavailable()
                _assert_document_binding(
                    document, context.tenant_id, citation.document_id
                )
                version = await unit_of_work.documents.get_version(
                    context.tenant_id,
                    citation.document_id,
                    citation.document_version,
                )
                if version is None:
                    raise _reference_unavailable()
                _assert_version_binding(version, document, citation.document_version)
                self._assert_available(document, version, now)
                try:
                    citation.assert_matches(version)
                except DomainViolation:
                    raise ApplicationError(
                        ErrorCode.KNOWLEDGE_REFERENCE_MISMATCH,
                        "stable citation integrity verification failed",
                    ) from None
                await self._authorize_read(
                    context,
                    KnowledgeOperation.QUERY,
                    document,
                    version,
                    now,
                )
                return KnowledgeCitationResolution(
                    citation=citation,
                    content_ref=version.content_ref,
                    data_classification=version.data_classification,
                )
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def diagnose(
        self,
        request: KnowledgeReadRequest,
    ) -> KnowledgeDiagnostic:
        now = self._now()
        KnowledgeCommandService._assert_context(request.context, now)
        try:
            async with self._unit_of_work() as unit_of_work:
                document = await unit_of_work.documents.get_document(
                    request.context.tenant_id,
                    request.document_id,
                )
                if document is None:
                    raise _not_found()
                _assert_document_binding(
                    document,
                    request.context.tenant_id,
                    request.document_id,
                )
                version_number = (
                    document.current_version
                    if request.document_version is None
                    else request.document_version
                )
                version = await unit_of_work.documents.get_version(
                    request.context.tenant_id,
                    request.document_id,
                    version_number,
                )
                if version is None:
                    raise _not_found()
                _assert_version_binding(version, document, version_number)
                await self._authorize_read(
                    request.context,
                    KnowledgeOperation.DIAGNOSTIC,
                    document,
                    version,
                    now,
                )
                diagnostic = await unit_of_work.index_jobs.diagnostic(
                    request.context.tenant_id,
                    request.document_id,
                    version_number,
                )
                if diagnostic is None:
                    raise _not_found()
                if (
                    diagnostic.tenant_id != document.tenant_id
                    or diagnostic.document_id != document.document_id
                    or diagnostic.document_version != version.version
                    or diagnostic.document_revision != document.revision
                    or diagnostic.content_hash != version.content_hash
                ):
                    raise ApplicationError(
                        ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
                        "knowledge diagnostic does not match document facts",
                    )
                return diagnostic
        except ApplicationError:
            raise
        except DomainViolation as exc:
            raise _map_domain_error(exc) from None
        except Exception:
            raise _repository_unavailable() from None

    async def _authorize_read(
        self,
        context: KnowledgeRequestContext,
        operation: KnowledgeOperation,
        document: KnowledgeDocument,
        version: DocumentVersion,
        now: datetime,
    ) -> None:
        await _authorize_exact(
            self._authorization,
            context=context,
            operation=operation,
            document_id=document.document_id,
            target_classification=version.data_classification,
            target_content_hash=version.content_hash,
            current_revision=document.revision,
            current_acl=version.access_control,
            target_acl=version.access_control,
            now=now,
        )

    @staticmethod
    def _assert_available(
        document: KnowledgeDocument,
        version: DocumentVersion,
        now: datetime,
    ) -> None:
        if (
            document.lifecycle is not KnowledgeLifecycle.ACTIVE
            or not version.is_effective(now)
        ):
            raise _reference_unavailable()

    def _now(self) -> datetime:
        observed = self._clock()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("knowledge query clock must be timezone-aware")
        return observed.astimezone(UTC)


async def _authorize_exact(
    authorization: KnowledgeAuthorizationPort,
    *,
    context: KnowledgeRequestContext,
    operation: KnowledgeOperation,
    document_id: str,
    target_classification: DataClassification,
    target_content_hash: str,
    current_revision: int | None,
    current_acl: KnowledgeAccessControl | None,
    target_acl: KnowledgeAccessControl,
    now: datetime,
) -> KnowledgeAuthorizationDecision:
    if not classification_allows(
        context.security_context.data_classification_ceiling,
        target_classification,
    ):
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_CLASSIFICATION_DENIED,
            "knowledge classification exceeds the trusted context ceiling",
        )
    if context.purpose not in target_acl.allowed_purposes or (
        current_acl is not None and context.purpose not in current_acl.allowed_purposes
    ):
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_PURPOSE_DENIED,
            "knowledge operation purpose is not allowed",
        )
    authorization_request = KnowledgeAuthorizationRequest(
        context=context,
        operation=operation,
        document_id=document_id,
        target_classification=target_classification,
        target_content_hash=target_content_hash,
        current_revision=current_revision,
        current_acl_digest=(None if current_acl is None else current_acl.digest()),
        target_acl_digest=target_acl.digest(),
    )
    try:
        decision = await authorization.authorize(authorization_request)
    except Exception:
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_AUTHORIZATION_UNAVAILABLE,
            "knowledge authorization is unavailable",
            retryable=True,
        ) from None
    if (
        not isinstance(decision, KnowledgeAuthorizationDecision)
        or decision.request_digest != authorization_request.digest()
        or decision.expires_at <= now
    ):
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_AUTHORIZATION_PROTOCOL_ERROR,
            "knowledge authorization returned an invalid binding",
        )
    if not decision.allowed:
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_AUTHORIZATION_DENIED,
            "knowledge operation was denied",
        )
    return decision


def _assert_document_binding(
    document: KnowledgeDocument,
    tenant_id: str,
    document_id: str,
) -> None:
    if document.tenant_id != tenant_id or document.document_id != document_id:
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
            "knowledge repository returned a cross-boundary document",
        )


def _assert_version_binding(
    version: DocumentVersion,
    document: KnowledgeDocument,
    expected_version: int,
) -> None:
    if (
        version.tenant_id != document.tenant_id
        or version.document_id != document.document_id
        or version.version != expected_version
    ):
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR,
            "knowledge repository returned a mismatched document version",
        )


def _content_ref(
    tenant_id: str,
    document_id: str,
    document_version: int,
    content_hash: str,
) -> str:
    seed = f"{tenant_id}\x00{document_id}\x00{document_version}\x00{content_hash}"
    return "knowledge-content://" + hashlib.sha256(seed.encode()).hexdigest()


def _map_domain_error(error: DomainViolation) -> ApplicationError:
    mapping = {
        DomainErrorCode.KNOWLEDGE_VERSION_CONFLICT: (
            ErrorCode.KNOWLEDGE_VERSION_CONFLICT
        ),
        DomainErrorCode.KNOWLEDGE_INVALID_STATE: (
            ErrorCode.KNOWLEDGE_LIFECYCLE_CONFLICT
        ),
        DomainErrorCode.KNOWLEDGE_REFERENCE_MISMATCH: (
            ErrorCode.KNOWLEDGE_REFERENCE_MISMATCH
        ),
        DomainErrorCode.KNOWLEDGE_CONTENT_HASH_MISMATCH: (
            ErrorCode.KNOWLEDGE_CONTRACT_INVALID
        ),
        DomainErrorCode.KNOWLEDGE_SOURCE_DIGEST_MISMATCH: (
            ErrorCode.KNOWLEDGE_CONTRACT_INVALID
        ),
    }
    return ApplicationError(
        mapping.get(error.code, ErrorCode.KNOWLEDGE_CONTRACT_INVALID),
        error.safe_message,
    )


def _repository_unavailable() -> ApplicationError:
    return ApplicationError(
        ErrorCode.KNOWLEDGE_REPOSITORY_UNAVAILABLE,
        "knowledge repository is unavailable",
        retryable=True,
    )


def _version_conflict() -> ApplicationError:
    return ApplicationError(
        ErrorCode.KNOWLEDGE_VERSION_CONFLICT,
        "knowledge document revision changed concurrently",
    )


def _lifecycle_conflict() -> ApplicationError:
    return ApplicationError(
        ErrorCode.KNOWLEDGE_LIFECYCLE_CONFLICT,
        "knowledge document lifecycle does not allow this operation",
    )


def _not_found() -> ApplicationError:
    return ApplicationError(
        ErrorCode.KNOWLEDGE_NOT_FOUND,
        "knowledge document was not found",
    )


def _reference_unavailable() -> ApplicationError:
    return ApplicationError(
        ErrorCode.KNOWLEDGE_REFERENCE_UNAVAILABLE,
        "stable citation is not available",
    )
