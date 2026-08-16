from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import wraps
from types import TracebackType
from typing import Any, Self

import pytest
from flowpilot_application import (
    ApplicationError,
    ErrorCode,
    KnowledgeAuthorizationDecision,
    KnowledgeAuthorizationRequest,
    KnowledgeCommandService,
    KnowledgeDiagnostic,
    KnowledgeIdempotencyClaim,
    KnowledgeIdempotencyDisposition,
    KnowledgeImportRequest,
    KnowledgeIndexJob,
    KnowledgeIndexOperation,
    KnowledgeIndexState,
    KnowledgeLifecycleRequest,
    KnowledgeOperation,
    KnowledgeOperationDisposition,
    KnowledgeOperationReceipt,
    KnowledgeOutboxEvent,
    KnowledgeQueryService,
    KnowledgeReadRequest,
    KnowledgeRebuildRequest,
    KnowledgeRepositoryDisposition,
    KnowledgeRequestContext,
    KnowledgeUpdateRequest,
)
from flowpilot_domain import (
    AclPrincipal,
    AclPrincipalType,
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    DocumentVersion,
    DomainErrorCode,
    DomainViolation,
    KnowledgeAccessControl,
    KnowledgeContent,
    KnowledgeDocument,
    KnowledgeLifecycle,
    KnowledgeSource,
    KnowledgeSourceType,
    SecurityContextRef,
    StableCitation,
    knowledge_content_hash,
)

NOW = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
ZERO_DIGEST = "sha256:" + "0" * 64
TENANT = "tenant-knowledge-a"
DOCUMENT_ID = "doc_knowledge0001"
BODY = "Approved runbook\nUse the documented recovery sequence."


def _async_test[**P, T](
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, T]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _security_context(
    *,
    tenant_id: str = TENANT,
    purpose: str = "support_resolution",
    ceiling: DataClassification = DataClassification.CONFIDENTIAL,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> SecurityContextRef:
    return SecurityContextRef(
        context_id="secctx_knowledge0001",
        context_ref="security-context://knowledge/one",
        context_hash="sha256:" + "1" * 64,
        tenant_id=tenant_id,
        subject_id="user-knowledge-owner",
        subject_type=ActorType.USER,
        purpose=purpose,
        authentication=AuthenticationRef(
            method=AuthenticationMethod.OIDC,
            assurance_level=AssuranceLevel.SUBSTANTIAL,
            session_id_hash="sha256:" + "2" * 64,
        ),
        data_classification_ceiling=ceiling,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=expires_at,
    )


def _context(
    *,
    tenant_id: str = TENANT,
    purpose: str = "support_resolution",
    trusted_tenant: str = TENANT,
    trusted_purpose: str = "support_resolution",
    ceiling: DataClassification = DataClassification.CONFIDENTIAL,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> KnowledgeRequestContext:
    return KnowledgeRequestContext(
        tenant_id=tenant_id,
        purpose=purpose,
        security_context=_security_context(
            tenant_id=trusted_tenant,
            purpose=trusted_purpose,
            ceiling=ceiling,
            expires_at=expires_at,
        ),
    )


def _acl(*, purpose: str = "support_resolution") -> KnowledgeAccessControl:
    return KnowledgeAccessControl(
        principals=(
            AclPrincipal(
                principal_type=AclPrincipalType.SUBJECT,
                principal_id="user-knowledge-owner",
            ),
        ),
        allowed_purposes=(purpose,),
    )


def _source(version: str = "source-v1") -> KnowledgeSource:
    return KnowledgeSource.build(
        source_type=KnowledgeSourceType.FILE,
        source_ref="source://controlled/runbook",
        source_version=version,
    )


def _import_request(
    *,
    context: KnowledgeRequestContext | None = None,
    content: KnowledgeContent | None = None,
    access_control: KnowledgeAccessControl | None = None,
    classification: DataClassification = DataClassification.CONFIDENTIAL,
    idempotency_key: str = "sha256:" + "3" * 64,
) -> KnowledgeImportRequest:
    request = KnowledgeImportRequest(
        context=context or _context(),
        document_id=DOCUMENT_ID,
        source=_source(),
        access_control=access_control or _acl(),
        data_classification=classification,
        effective_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=30),
        content=content or KnowledgeContent.from_text(BODY),
        idempotency_key=idempotency_key,
        request_digest=ZERO_DIGEST,
    )
    return replace(request, request_digest=request.recompute_digest())


def _update_request(
    *,
    body: str = "Approved runbook version two.",
    expected_revision: int = 0,
    idempotency_key: str = "sha256:" + "4" * 64,
) -> KnowledgeUpdateRequest:
    request = KnowledgeUpdateRequest(
        context=_context(),
        document_id=DOCUMENT_ID,
        expected_revision=expected_revision,
        source=_source("source-v2"),
        access_control=_acl(),
        data_classification=DataClassification.CONFIDENTIAL,
        effective_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=31),
        content=KnowledgeContent.from_text(body),
        idempotency_key=idempotency_key,
        request_digest=ZERO_DIGEST,
    )
    return replace(request, request_digest=request.recompute_digest())


def _lifecycle_request(
    operation: KnowledgeOperation,
    *,
    expected_revision: int,
    idempotency_digit: str,
) -> KnowledgeLifecycleRequest:
    request = KnowledgeLifecycleRequest(
        context=_context(),
        document_id=DOCUMENT_ID,
        expected_revision=expected_revision,
        idempotency_key="sha256:" + idempotency_digit * 64,
        request_digest=ZERO_DIGEST,
    )
    return replace(request, request_digest=request.recompute_digest(operation))


@dataclass(slots=True)
class _Store:
    documents: dict[tuple[str, str], KnowledgeDocument] = field(default_factory=dict)
    versions: dict[tuple[str, str, int], DocumentVersion] = field(default_factory=dict)
    bodies: dict[tuple[str, str, int], str] = field(default_factory=dict)
    inbox: dict[
        tuple[str, str],
        tuple[str, KnowledgeOperationReceipt | None],
    ] = field(default_factory=dict)
    events: list[KnowledgeOutboxEvent] = field(default_factory=list)
    jobs: dict[str, KnowledgeIndexJob] = field(default_factory=dict)
    diagnostics: dict[tuple[str, str, int], KnowledgeDiagnostic] = field(
        default_factory=dict
    )

    def clone(self) -> _Store:
        return _Store(
            documents=dict(self.documents),
            versions=dict(self.versions),
            bodies=dict(self.bodies),
            inbox=dict(self.inbox),
            events=list(self.events),
            jobs=dict(self.jobs),
            diagnostics=dict(self.diagnostics),
        )

    def replace_with(self, other: _Store) -> None:
        self.documents = other.documents
        self.versions = other.versions
        self.bodies = other.bodies
        self.inbox = other.inbox
        self.events = other.events
        self.jobs = other.jobs
        self.diagnostics = other.diagnostics


class _Repository:
    def __init__(self, store: _Store, factory: _UnitOfWorkFactory) -> None:
        self._store = store
        self._factory = factory

    async def get_document(
        self,
        tenant_id: str,
        document_id: str,
        *,
        for_update: bool = False,
    ) -> KnowledgeDocument | None:
        del for_update
        value = self._store.documents.get((tenant_id, document_id))
        if value is not None and self._factory.cross_tenant_projection:
            return replace(value, tenant_id="tenant-cross-boundary")
        return value

    async def get_version(
        self,
        tenant_id: str,
        document_id: str,
        document_version: int,
    ) -> DocumentVersion | None:
        return self._store.versions.get((tenant_id, document_id, document_version))

    async def add(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion,
        content: KnowledgeContent,
    ) -> KnowledgeRepositoryDisposition:
        key = (document.tenant_id, document.document_id)
        if key in self._store.documents:
            return KnowledgeRepositoryDisposition.CONFLICT
        self._store.documents[key] = document
        version_key = (*key, version.version)
        self._store.versions[version_key] = version
        self._store.bodies[version_key] = content.text
        return KnowledgeRepositoryDisposition.APPLIED

    async def update(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion,
        content: KnowledgeContent,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition:
        key = (document.tenant_id, document.document_id)
        existing = self._store.documents.get(key)
        if existing is None or existing.revision != expected_revision:
            return KnowledgeRepositoryDisposition.CONFLICT
        self._store.documents[key] = document
        version_key = (*key, version.version)
        self._store.versions[version_key] = version
        self._store.bodies[version_key] = content.text
        return KnowledgeRepositoryDisposition.APPLIED

    async def retire(
        self,
        document: KnowledgeDocument,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition:
        return self._transition(document, expected_revision, delete=False)

    async def delete(
        self,
        document: KnowledgeDocument,
        *,
        expected_revision: int,
    ) -> KnowledgeRepositoryDisposition:
        return self._transition(document, expected_revision, delete=True)

    def _transition(
        self,
        document: KnowledgeDocument,
        expected_revision: int,
        *,
        delete: bool,
    ) -> KnowledgeRepositoryDisposition:
        key = (document.tenant_id, document.document_id)
        existing = self._store.documents.get(key)
        if existing is None or existing.revision != expected_revision:
            return KnowledgeRepositoryDisposition.CONFLICT
        self._store.documents[key] = document
        if delete:
            for body_key in tuple(self._store.bodies):
                if body_key[:2] == key:
                    del self._store.bodies[body_key]
        return KnowledgeRepositoryDisposition.APPLIED


class _Inbox:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def claim(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> KnowledgeIdempotencyClaim:
        key = (tenant_id, idempotency_key)
        existing = self._store.inbox.get(key)
        if existing is None:
            self._store.inbox[key] = (request_digest, None)
            return KnowledgeIdempotencyClaim(KnowledgeIdempotencyDisposition.CLAIMED)
        digest, receipt = existing
        if digest != request_digest:
            return KnowledgeIdempotencyClaim(KnowledgeIdempotencyDisposition.CONFLICT)
        if receipt is None:
            raise RuntimeError("incomplete in-transaction idempotency record")
        return KnowledgeIdempotencyClaim(
            KnowledgeIdempotencyDisposition.DUPLICATE,
            receipt,
        )

    async def complete(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_digest: str,
        receipt: KnowledgeOperationReceipt,
    ) -> None:
        key = (tenant_id, idempotency_key)
        if self._store.inbox.get(key) != (request_digest, None):
            raise RuntimeError("idempotency completion mismatch")
        self._store.inbox[key] = (request_digest, receipt)


class _Outbox:
    def __init__(self, store: _Store, factory: _UnitOfWorkFactory) -> None:
        self._store = store
        self._factory = factory

    async def add(self, event: KnowledgeOutboxEvent) -> None:
        if self._factory.outbox_failure:
            raise RuntimeError(f"database rejected hidden body: {BODY}")
        self._store.events.append(event)


class _IndexJobs:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def enqueue(self, job: KnowledgeIndexJob) -> bool:
        existing = self._store.jobs.get(job.job_id)
        if existing is not None:
            return False
        self._store.jobs[job.job_id] = job
        self._store.diagnostics[
            (job.tenant_id, job.document_id, job.document_version)
        ] = KnowledgeDiagnostic(
            tenant_id=job.tenant_id,
            document_id=job.document_id,
            document_version=job.document_version,
            document_revision=job.document_revision,
            content_hash=job.content_hash,
            index_state=KnowledgeIndexState.PENDING,
            last_job_id=job.job_id,
        )
        return True

    async def diagnostic(
        self,
        tenant_id: str,
        document_id: str,
        document_version: int,
    ) -> KnowledgeDiagnostic | None:
        return self._store.diagnostics.get((tenant_id, document_id, document_version))


class _UnitOfWork:
    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        self._factory = factory
        self._working: _Store | None = None
        self._committed = False
        self.documents: _Repository
        self.inbox: _Inbox
        self.outbox: _Outbox
        self.index_jobs: _IndexJobs

    async def __aenter__(self) -> Self:
        self._working = self._factory.store.clone()
        self.documents = _Repository(self._working, self._factory)
        self.inbox = _Inbox(self._working)
        self.outbox = _Outbox(self._working, self._factory)
        self.index_jobs = _IndexJobs(self._working)
        self._committed = False
        self._factory.entries += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None and self._committed and self._working is not None:
            self._factory.store.replace_with(self._working)
        self._working = None

    async def commit(self) -> None:
        self._committed = True


class _UnitOfWorkFactory:
    def __init__(self) -> None:
        self.store = _Store()
        self.entries = 0
        self.outbox_failure = False
        self.cross_tenant_projection = False

    def __call__(self) -> _UnitOfWork:
        return _UnitOfWork(self)


class _Authorization:
    def __init__(self) -> None:
        self.calls: list[KnowledgeAuthorizationRequest] = []
        self.allowed = True
        self.invalid_binding = False
        self.failure = False

    async def authorize(
        self,
        request: KnowledgeAuthorizationRequest,
    ) -> KnowledgeAuthorizationDecision:
        self.calls.append(request)
        if self.failure:
            raise RuntimeError(f"provider leaked content: {BODY}")
        request_digest = ZERO_DIGEST if self.invalid_binding else request.digest()
        return KnowledgeAuthorizationDecision(
            allowed=self.allowed,
            request_digest=request_digest,
            decision_id="policy-decision-knowledge-001",
            policy_version="knowledge-policy-v1",
            expires_at=NOW + timedelta(minutes=30),
        )


class _ContentSafety:
    def __init__(self) -> None:
        self.calls = 0
        self.failure = False

    def assert_safe(self, content: str) -> None:
        self.calls += 1
        if self.failure:
            raise RuntimeError(f"unsafe content: {content}")


@dataclass(slots=True)
class _Harness:
    unit_of_work: _UnitOfWorkFactory
    authorization: _Authorization
    safety: _ContentSafety
    commands: KnowledgeCommandService
    queries: KnowledgeQueryService


def _harness() -> _Harness:
    unit_of_work = _UnitOfWorkFactory()
    authorization = _Authorization()
    safety = _ContentSafety()
    return _Harness(
        unit_of_work=unit_of_work,
        authorization=authorization,
        safety=safety,
        commands=KnowledgeCommandService(
            unit_of_work=unit_of_work,
            authorization=authorization,
            content_safety=safety,
            clock=lambda: NOW,
        ),
        queries=KnowledgeQueryService(
            unit_of_work=unit_of_work,
            authorization=authorization,
            clock=lambda: NOW,
        ),
    )


def test_content_normalization_hash_and_repr_are_body_safe() -> None:
    content = KnowledgeContent.from_text("Cafe\u0301\r\nrunbook")

    assert content.text == "Caf\u00e9\nrunbook"
    assert content.content_hash == knowledge_content_hash("Caf\u00e9\nrunbook")
    assert content.text not in repr(content)

    with pytest.raises(DomainViolation) as exc_info:
        KnowledgeContent(text="different", content_hash=content.content_hash)
    assert exc_info.value.code is DomainErrorCode.KNOWLEDGE_CONTENT_HASH_MISMATCH
    assert "different" not in exc_info.value.safe_message


def test_initial_version_and_lifecycle_use_separate_zero_based_counters() -> None:
    content = KnowledgeContent.from_text(BODY)
    version = DocumentVersion(
        tenant_id=TENANT,
        document_id=DOCUMENT_ID,
        version=0,
        source=_source(),
        access_control=_acl(),
        data_classification=DataClassification.CONFIDENTIAL,
        effective_at=NOW,
        expires_at=None,
        content_ref="knowledge-content://initial",
        content_hash=content.content_hash,
        created_at=NOW,
    )
    document = KnowledgeDocument.start(version)

    assert document.revision == 0
    assert document.current_version == 0
    assert document.lifecycle is KnowledgeLifecycle.ACTIVE

    with pytest.raises(DomainViolation) as exc_info:
        KnowledgeDocument.start(replace(version, version=1))
    assert exc_info.value.code is DomainErrorCode.KNOWLEDGE_VERSION_CONFLICT


def test_stable_citation_requires_exact_version_and_hash() -> None:
    content = KnowledgeContent.from_text(BODY)
    version = DocumentVersion(
        tenant_id=TENANT,
        document_id=DOCUMENT_ID,
        version=0,
        source=_source(),
        access_control=_acl(),
        data_classification=DataClassification.INTERNAL,
        effective_at=NOW,
        expires_at=None,
        content_ref="knowledge-content://initial",
        content_hash=content.content_hash,
        created_at=NOW,
    )
    citation = version.citation("section.recovery")
    citation.assert_matches(version)

    with pytest.raises(DomainViolation) as exc_info:
        replace(citation, content_hash="sha256:" + "f" * 64).assert_matches(version)
    assert exc_info.value.code is DomainErrorCode.KNOWLEDGE_REFERENCE_MISMATCH


@_async_test
async def test_import_is_atomic_and_emits_metadata_only() -> None:
    harness = _harness()

    receipt = await harness.commands.import_document(_import_request())

    document = harness.unit_of_work.store.documents[(TENANT, DOCUMENT_ID)]
    version = harness.unit_of_work.store.versions[(TENANT, DOCUMENT_ID, 0)]
    event = harness.unit_of_work.store.events[0]
    assert receipt.disposition is KnowledgeOperationDisposition.APPLIED
    assert (document.revision, document.current_version) == (0, 0)
    assert version.content_hash == KnowledgeContent.from_text(BODY).content_hash
    assert harness.unit_of_work.store.bodies[(TENANT, DOCUMENT_ID, 0)] == BODY
    assert len(harness.unit_of_work.store.jobs) == 1
    assert BODY not in repr(event)
    assert BODY not in repr(event.safe_payload())
    assert "source://controlled/runbook" not in repr(event)


@_async_test
async def test_identical_replay_is_duplicate_without_new_writes() -> None:
    harness = _harness()
    request = _import_request()
    first = await harness.commands.import_document(request)

    replay = await harness.commands.import_document(request)

    assert first.disposition is KnowledgeOperationDisposition.APPLIED
    assert replay.disposition is KnowledgeOperationDisposition.DUPLICATE
    assert replay.event_id == first.event_id
    assert len(harness.unit_of_work.store.events) == 1
    assert len(harness.unit_of_work.store.jobs) == 1


@_async_test
async def test_same_idempotency_key_with_different_digest_conflicts() -> None:
    harness = _harness()
    first = _import_request()
    await harness.commands.import_document(first)
    changed = _import_request(content=KnowledgeContent.from_text("changed body"))

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.import_document(changed)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_IDEMPOTENCY_CONFLICT
    assert len(harness.unit_of_work.store.events) == 1
    assert "changed body" not in exc_info.value.safe_message


@_async_test
async def test_update_appends_version_and_old_citation_never_redirects() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())
    old_version = harness.unit_of_work.store.versions[(TENANT, DOCUMENT_ID, 0)]
    old_citation = old_version.citation("recovery.step")

    receipt = await harness.commands.update_document(_update_request())
    resolution = await harness.queries.resolve_citation(_context(), old_citation)

    assert (receipt.revision, receipt.document_version) == (1, 1)
    assert resolution.content_ref == old_version.content_ref
    assert (
        resolution.content_ref
        != harness.unit_of_work.store.versions[(TENANT, DOCUMENT_ID, 1)].content_ref
    )


@_async_test
async def test_stale_update_revision_rolls_back_idempotency_claim() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())
    await harness.commands.update_document(_update_request())
    stale = _update_request(
        body="stale update",
        expected_revision=0,
        idempotency_key="sha256:" + "5" * 64,
    )

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.update_document(stale)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_CONFLICT
    assert (TENANT, stale.idempotency_key) not in harness.unit_of_work.store.inbox
    assert len(harness.unit_of_work.store.versions) == 2


@_async_test
async def test_retire_then_delete_is_explicit_and_delete_erases_bodies() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())
    citation = harness.unit_of_work.store.versions[(TENANT, DOCUMENT_ID, 0)].citation(
        "recovery"
    )
    retired = await harness.commands.retire_document(
        _lifecycle_request(
            KnowledgeOperation.RETIRE,
            expected_revision=0,
            idempotency_digit="6",
        )
    )

    with pytest.raises(ApplicationError) as query_error:
        await harness.queries.resolve_citation(_context(), citation)
    assert query_error.value.code is ErrorCode.KNOWLEDGE_REFERENCE_UNAVAILABLE

    deleted = await harness.commands.delete_document(
        _lifecycle_request(
            KnowledgeOperation.DELETE,
            expected_revision=1,
            idempotency_digit="7",
        )
    )
    assert (retired.revision, deleted.revision) == (1, 2)
    assert not harness.unit_of_work.store.bodies
    assert harness.unit_of_work.store.documents[(TENANT, DOCUMENT_ID)].lifecycle is (
        KnowledgeLifecycle.DELETED
    )


@_async_test
async def test_second_non_replay_retire_is_invalid_lifecycle() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())
    await harness.commands.retire_document(
        _lifecycle_request(
            KnowledgeOperation.RETIRE,
            expected_revision=0,
            idempotency_digit="6",
        )
    )
    second = _lifecycle_request(
        KnowledgeOperation.RETIRE,
        expected_revision=1,
        idempotency_digit="8",
    )

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.retire_document(second)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_LIFECYCLE_CONFLICT
    assert (TENANT, second.idempotency_key) not in harness.unit_of_work.store.inbox


@_async_test
async def test_rebuild_requires_exact_current_version_and_revision() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())
    request = KnowledgeRebuildRequest(
        context=_context(),
        document_id=DOCUMENT_ID,
        expected_revision=0,
        document_version=1,
        idempotency_key="sha256:" + "9" * 64,
        request_digest=ZERO_DIGEST,
    )
    request = replace(request, request_digest=request.recompute_digest())

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.rebuild_document(request)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_CONFLICT
    assert len(harness.unit_of_work.store.jobs) == 1


@_async_test
@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (
            _context(tenant_id="tenant-forged", trusted_tenant=TENANT),
            ErrorCode.KNOWLEDGE_TENANT_MISMATCH,
        ),
        (
            _context(purpose="forged", trusted_purpose="support_resolution"),
            ErrorCode.KNOWLEDGE_PURPOSE_DENIED,
        ),
        (
            _context(expires_at=NOW),
            ErrorCode.KNOWLEDGE_AUTHORIZATION_DENIED,
        ),
    ],
)
async def test_trusted_context_mismatch_fails_before_persistence(
    context: KnowledgeRequestContext,
    expected: ErrorCode,
) -> None:
    harness = _harness()

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.import_document(_import_request(context=context))

    assert exc_info.value.code is expected
    assert harness.unit_of_work.entries == 0
    assert not harness.authorization.calls


@_async_test
async def test_wrong_acl_purpose_and_classification_fail_closed() -> None:
    purpose_harness = _harness()
    with pytest.raises(ApplicationError) as purpose_error:
        await purpose_harness.commands.import_document(
            _import_request(access_control=_acl(purpose="audit"))
        )
    assert purpose_error.value.code is ErrorCode.KNOWLEDGE_PURPOSE_DENIED
    assert purpose_harness.unit_of_work.entries == 0

    classification_harness = _harness()
    with pytest.raises(ApplicationError) as classification_error:
        await classification_harness.commands.import_document(
            _import_request(
                context=_context(ceiling=DataClassification.INTERNAL),
                classification=DataClassification.RESTRICTED,
            )
        )
    assert classification_error.value.code is ErrorCode.KNOWLEDGE_CLASSIFICATION_DENIED
    assert classification_harness.unit_of_work.entries == 0


@_async_test
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("deny", ErrorCode.KNOWLEDGE_AUTHORIZATION_DENIED),
        ("invalid", ErrorCode.KNOWLEDGE_AUTHORIZATION_PROTOCOL_ERROR),
        ("failure", ErrorCode.KNOWLEDGE_AUTHORIZATION_UNAVAILABLE),
    ],
)
async def test_policy_failure_modes_are_stable_and_write_nothing(
    mode: str,
    expected: ErrorCode,
) -> None:
    harness = _harness()
    harness.authorization.allowed = mode != "deny"
    harness.authorization.invalid_binding = mode == "invalid"
    harness.authorization.failure = mode == "failure"

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.import_document(_import_request())

    assert exc_info.value.code is expected
    assert not harness.unit_of_work.store.documents
    assert BODY not in exc_info.value.safe_message


@_async_test
async def test_unsafe_content_is_redacted_and_never_opens_transaction() -> None:
    harness = _harness()
    harness.safety.failure = True

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.import_document(_import_request())

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_CONTENT_UNSAFE
    assert BODY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert harness.unit_of_work.entries == 0


@_async_test
async def test_outbox_failure_rolls_back_document_inbox_and_index_job() -> None:
    harness = _harness()
    harness.unit_of_work.outbox_failure = True

    with pytest.raises(ApplicationError) as exc_info:
        await harness.commands.import_document(_import_request())

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_REPOSITORY_UNAVAILABLE
    assert exc_info.value.__cause__ is None
    assert BODY not in str(exc_info.value)
    assert not harness.unit_of_work.store.documents
    assert not harness.unit_of_work.store.inbox
    assert not harness.unit_of_work.store.jobs
    assert not harness.unit_of_work.store.events


@_async_test
async def test_repository_cross_tenant_projection_is_rejected() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())
    harness.unit_of_work.cross_tenant_projection = True

    with pytest.raises(ApplicationError) as exc_info:
        await harness.queries.get_document(
            KnowledgeReadRequest(context=_context(), document_id=DOCUMENT_ID)
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR


@_async_test
async def test_query_respects_effective_and_expiry_window() -> None:
    harness = _harness()
    request = _import_request()
    request = replace(
        request,
        effective_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=2),
    )
    request = replace(request, request_digest=request.recompute_digest())
    await harness.commands.import_document(request)

    with pytest.raises(ApplicationError) as exc_info:
        await harness.queries.get_document(
            KnowledgeReadRequest(context=_context(), document_id=DOCUMENT_ID)
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_REFERENCE_UNAVAILABLE


@_async_test
async def test_diagnostic_is_bound_to_document_version_and_revision() -> None:
    harness = _harness()
    await harness.commands.import_document(_import_request())

    diagnostic = await harness.queries.diagnose(
        KnowledgeReadRequest(context=_context(), document_id=DOCUMENT_ID)
    )

    assert diagnostic.index_state is KnowledgeIndexState.PENDING
    assert (diagnostic.document_version, diagnostic.document_revision) == (0, 0)
    job = next(iter(harness.unit_of_work.store.jobs.values()))
    assert job.operation is KnowledgeIndexOperation.UPSERT


def test_source_and_event_repr_do_not_disclose_source_or_body() -> None:
    source = _source()
    assert "source://controlled/runbook" not in repr(source)

    citation = StableCitation(
        tenant_id=TENANT,
        document_id=DOCUMENT_ID,
        document_version=0,
        section_id="section-one",
        content_hash=knowledge_content_hash(BODY),
    )
    assert citation.to_mapping()["document_version"] == 0
