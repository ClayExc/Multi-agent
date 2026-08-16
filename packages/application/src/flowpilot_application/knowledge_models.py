from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from flowpilot_domain import (
    DataClassification,
    DocumentVersion,
    KnowledgeAccessControl,
    KnowledgeContent,
    KnowledgeDocument,
    KnowledgeSource,
    SecurityContextRef,
    StableCitation,
    canonical_sha256,
)

KNOWLEDGE_APPLICATION_PORT_VERSION = "flowpilot.knowledge-ports.m10.v2"

_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class KnowledgeOperation(StrEnum):
    IMPORT = "import"
    UPDATE = "update"
    RETIRE = "retire"
    DELETE = "delete"
    REBUILD = "rebuild"
    QUERY = "query"
    DIAGNOSTIC = "diagnostic"


class KnowledgeOperationDisposition(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"


class KnowledgeRepositoryDisposition(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"


class KnowledgeIdempotencyDisposition(StrEnum):
    CLAIMED = "claimed"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


class KnowledgeIndexOperation(StrEnum):
    UPSERT = "upsert"
    REMOVE = "remove"
    REBUILD = "rebuild"


class KnowledgeIndexState(StrEnum):
    MISSING = "missing"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    REMOVED = "removed"


class KnowledgeEventType(StrEnum):
    IMPORTED = "knowledge.document.imported.v1"
    UPDATED = "knowledge.document.updated.v1"
    RETIRED = "knowledge.document.retired.v1"
    DELETED = "knowledge.document.deleted.v1"
    REBUILD_REQUESTED = "knowledge.index.rebuild.requested.v1"


@dataclass(frozen=True, slots=True)
class KnowledgeRequestContext:
    """Server-built identity binding; never deserialize it from a request body."""

    tenant_id: str
    purpose: str
    security_context: SecurityContextRef = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "knowledge_context.tenant_id", 128)
        _require_text(self.purpose, "knowledge_context.purpose", 256)
        if not isinstance(self.security_context, SecurityContextRef):
            raise ValueError("knowledge_context.security_context is invalid")

    def safe_mapping(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "purpose": self.purpose,
            "security_context_ref": self.security_context.context_ref,
            "security_context_hash": self.security_context.context_hash,
            "subject_id": self.security_context.subject_id,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeAuthorizationRequest:
    context: KnowledgeRequestContext
    operation: KnowledgeOperation
    document_id: str
    target_classification: DataClassification
    target_content_hash: str
    current_revision: int | None
    current_acl_digest: str | None
    target_acl_digest: str

    def __post_init__(self) -> None:
        _require_document_id(self.document_id)
        if not isinstance(self.operation, KnowledgeOperation):
            raise ValueError("knowledge authorization operation is invalid")
        if not isinstance(self.target_classification, DataClassification):
            raise ValueError("knowledge authorization classification is invalid")
        _require_sha256(self.target_content_hash, "target_content_hash")
        _require_optional_revision(self.current_revision)
        if self.current_acl_digest is not None:
            _require_sha256(self.current_acl_digest, "current_acl_digest")
        _require_sha256(self.target_acl_digest, "target_acl_digest")

    def digest(self) -> str:
        return canonical_sha256(
            {
                "context": self.context.safe_mapping(),
                "operation": self.operation.value,
                "document_id": self.document_id,
                "target_classification": self.target_classification.value,
                "target_content_hash": self.target_content_hash,
                "current_revision": self.current_revision,
                "current_acl_digest": self.current_acl_digest,
                "target_acl_digest": self.target_acl_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class KnowledgeAuthorizationDecision:
    allowed: bool
    request_digest: str
    decision_id: str
    policy_version: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("authorization decision must be boolean")
        _require_sha256(self.request_digest, "authorization.request_digest")
        _require_text(self.decision_id, "authorization.decision_id", 256)
        _require_text(self.policy_version, "authorization.policy_version", 128)
        object.__setattr__(self, "expires_at", _utc(self.expires_at, "expires_at"))


@dataclass(frozen=True, slots=True)
class KnowledgeImportRequest:
    context: KnowledgeRequestContext
    document_id: str
    source: KnowledgeSource
    access_control: KnowledgeAccessControl
    data_classification: DataClassification
    effective_at: datetime
    expires_at: datetime | None
    content: KnowledgeContent = field(repr=False)
    idempotency_key: str
    request_digest: str

    def __post_init__(self) -> None:
        _validate_version_input(
            self.context,
            self.document_id,
            self.source,
            self.access_control,
            self.data_classification,
            self.effective_at,
            self.expires_at,
            self.content,
        )
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.request_digest, "request_digest")

    def recompute_digest(self) -> str:
        return _version_request_digest(self, operation=KnowledgeOperation.IMPORT)


@dataclass(frozen=True, slots=True)
class KnowledgeUpdateRequest:
    context: KnowledgeRequestContext
    document_id: str
    expected_revision: int
    source: KnowledgeSource
    access_control: KnowledgeAccessControl
    data_classification: DataClassification
    effective_at: datetime
    expires_at: datetime | None
    content: KnowledgeContent = field(repr=False)
    idempotency_key: str
    request_digest: str

    def __post_init__(self) -> None:
        _validate_version_input(
            self.context,
            self.document_id,
            self.source,
            self.access_control,
            self.data_classification,
            self.effective_at,
            self.expires_at,
            self.content,
        )
        _require_revision(self.expected_revision, "expected_revision")
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.request_digest, "request_digest")

    def recompute_digest(self) -> str:
        return _version_request_digest(
            self,
            operation=KnowledgeOperation.UPDATE,
            expected_revision=self.expected_revision,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeLifecycleRequest:
    context: KnowledgeRequestContext
    document_id: str
    expected_revision: int
    idempotency_key: str
    request_digest: str

    def __post_init__(self) -> None:
        _require_document_id(self.document_id)
        _require_revision(self.expected_revision, "expected_revision")
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.request_digest, "request_digest")

    def recompute_digest(self, operation: KnowledgeOperation) -> str:
        if operation not in {KnowledgeOperation.RETIRE, KnowledgeOperation.DELETE}:
            raise ValueError("lifecycle request operation is invalid")
        return canonical_sha256(
            {
                "operation": operation.value,
                "context": self.context.safe_mapping(),
                "document_id": self.document_id,
                "expected_revision": self.expected_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class KnowledgeRebuildRequest:
    context: KnowledgeRequestContext
    document_id: str
    expected_revision: int
    document_version: int
    idempotency_key: str
    request_digest: str

    def __post_init__(self) -> None:
        _require_document_id(self.document_id)
        _require_revision(self.expected_revision, "expected_revision")
        _require_revision(self.document_version, "document_version")
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.request_digest, "request_digest")

    def recompute_digest(self) -> str:
        return canonical_sha256(
            {
                "operation": KnowledgeOperation.REBUILD.value,
                "context": self.context.safe_mapping(),
                "document_id": self.document_id,
                "expected_revision": self.expected_revision,
                "document_version": self.document_version,
            }
        )


@dataclass(frozen=True, slots=True)
class KnowledgeReadRequest:
    context: KnowledgeRequestContext
    document_id: str
    document_version: int | None = None

    def __post_init__(self) -> None:
        _require_document_id(self.document_id)
        _require_optional_revision(self.document_version)


@dataclass(frozen=True, slots=True)
class KnowledgeOperationReceipt:
    tenant_id: str
    document_id: str
    operation: KnowledgeOperation
    revision: int
    document_version: int
    disposition: KnowledgeOperationDisposition
    event_id: str
    index_job_id: str

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "receipt.tenant_id", 128)
        _require_document_id(self.document_id)
        if not isinstance(self.operation, KnowledgeOperation):
            raise ValueError("receipt.operation is invalid")
        _require_revision(self.revision, "receipt.revision")
        _require_revision(self.document_version, "receipt.document_version")
        if not isinstance(self.disposition, KnowledgeOperationDisposition):
            raise ValueError("receipt.disposition is invalid")
        _require_text(self.event_id, "receipt.event_id", 256)
        _require_text(self.index_job_id, "receipt.index_job_id", 256)


@dataclass(frozen=True, slots=True)
class KnowledgeIdempotencyClaim:
    disposition: KnowledgeIdempotencyDisposition
    receipt: KnowledgeOperationReceipt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, KnowledgeIdempotencyDisposition):
            raise ValueError("idempotency disposition is invalid")
        if self.disposition is KnowledgeIdempotencyDisposition.DUPLICATE:
            if self.receipt is None:
                raise ValueError("duplicate idempotency claim requires a receipt")
        elif self.receipt is not None:
            raise ValueError(
                "non-duplicate idempotency claim must not contain a receipt"
            )


@dataclass(frozen=True, slots=True)
class KnowledgeIndexJob:
    job_id: str
    tenant_id: str
    document_id: str
    document_version: int
    document_revision: int
    content_hash: str
    operation: KnowledgeIndexOperation
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.job_id, "index_job.job_id", 256)
        _require_text(self.tenant_id, "index_job.tenant_id", 128)
        _require_document_id(self.document_id)
        _require_revision(self.document_version, "index_job.document_version")
        _require_revision(self.document_revision, "index_job.document_revision")
        _require_sha256(self.content_hash, "index_job.content_hash")
        if not isinstance(self.operation, KnowledgeIndexOperation):
            raise ValueError("index_job.operation is invalid")
        object.__setattr__(
            self,
            "requested_at",
            _utc(self.requested_at, "index_job.requested_at"),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeOutboxEvent:
    event_id: str
    event_type: KnowledgeEventType
    tenant_id: str
    document_id: str
    document_version: int
    document_revision: int
    content_hash: str
    data_classification: DataClassification
    acl_digest: str
    policy_decision_id: str
    policy_version: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.event_id, "knowledge_event.event_id", 256)
        if not isinstance(self.event_type, KnowledgeEventType):
            raise ValueError("knowledge_event.event_type is invalid")
        _require_text(self.tenant_id, "knowledge_event.tenant_id", 128)
        _require_document_id(self.document_id)
        _require_revision(self.document_version, "document_version")
        _require_revision(self.document_revision, "document_revision")
        _require_sha256(self.content_hash, "content_hash")
        if not isinstance(self.data_classification, DataClassification):
            raise ValueError("knowledge_event.data_classification is invalid")
        _require_sha256(self.acl_digest, "acl_digest")
        _require_text(self.policy_decision_id, "policy_decision_id", 256)
        _require_text(self.policy_version, "policy_version", 128)
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at, "occurred_at"))

    def safe_payload(self) -> dict[str, str | int]:
        return {
            "document_id": self.document_id,
            "document_version": self.document_version,
            "document_revision": self.document_revision,
            "content_hash": self.content_hash,
            "data_classification": self.data_classification.value,
            "acl_digest": self.acl_digest,
            "policy_decision_id": self.policy_decision_id,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentProjection:
    document: KnowledgeDocument
    version: DocumentVersion

    def __post_init__(self) -> None:
        if (
            self.document.tenant_id != self.version.tenant_id
            or self.document.document_id != self.version.document_id
            or self.document.current_version < self.version.version
        ):
            raise ValueError("knowledge projection contains mismatched records")


@dataclass(frozen=True, slots=True)
class KnowledgeContentProjection:
    """Exact-version content excerpt loaded only after citation authorization."""

    tenant_id: str
    document_id: str
    document_version: int
    content_ref: str
    content_hash: str
    data_classification: DataClassification
    content_excerpt: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "content_projection.tenant_id", 128)
        _require_document_id(self.document_id)
        _require_revision(self.document_version, "content_projection.document_version")
        _require_text(self.content_ref, "content_projection.content_ref", 512)
        _require_sha256(self.content_hash, "content_projection.content_hash")
        if not isinstance(self.data_classification, DataClassification):
            raise ValueError("content_projection.data_classification is invalid")
        _require_text(self.content_excerpt, "content_projection.content_excerpt", 2048)


@dataclass(frozen=True, slots=True)
class KnowledgeCitationResolution:
    citation: StableCitation
    content_ref: str
    data_classification: DataClassification
    content_excerpt: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.content_ref, "citation_resolution.content_ref", 512)
        if not isinstance(self.data_classification, DataClassification):
            raise ValueError("citation_resolution.data_classification is invalid")
        _require_text(self.content_excerpt, "citation_resolution.content_excerpt", 2048)


@dataclass(frozen=True, slots=True)
class KnowledgeDiagnostic:
    tenant_id: str
    document_id: str
    document_version: int
    document_revision: int
    content_hash: str
    index_state: KnowledgeIndexState
    last_job_id: str | None = None
    indexed_at: datetime | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "diagnostic.tenant_id", 128)
        _require_document_id(self.document_id)
        _require_revision(self.document_version, "diagnostic.document_version")
        _require_revision(self.document_revision, "diagnostic.document_revision")
        _require_sha256(self.content_hash, "diagnostic.content_hash")
        if not isinstance(self.index_state, KnowledgeIndexState):
            raise ValueError("diagnostic.index_state is invalid")
        if self.last_job_id is not None:
            _require_text(self.last_job_id, "diagnostic.last_job_id", 256)
        if self.indexed_at is not None:
            object.__setattr__(self, "indexed_at", _utc(self.indexed_at, "indexed_at"))
        if self.failure_code is not None:
            _require_text(self.failure_code, "diagnostic.failure_code", 128)


def classification_allows(
    ceiling: DataClassification,
    classification: DataClassification,
) -> bool:
    return _CLASSIFICATION_RANK[classification] <= _CLASSIFICATION_RANK[ceiling]


def _version_request_digest(
    request: KnowledgeImportRequest | KnowledgeUpdateRequest,
    *,
    operation: KnowledgeOperation,
    expected_revision: int | None = None,
) -> str:
    return canonical_sha256(
        {
            "operation": operation.value,
            "context": request.context.safe_mapping(),
            "document_id": request.document_id,
            "expected_revision": expected_revision,
            "source": request.source.safe_mapping(),
            "acl_digest": request.access_control.digest(),
            "data_classification": request.data_classification.value,
            "effective_at": _format_utc(request.effective_at),
            "expires_at": (
                None if request.expires_at is None else _format_utc(request.expires_at)
            ),
            "content_hash": request.content.content_hash,
        }
    )


def _validate_version_input(
    context: KnowledgeRequestContext,
    document_id: str,
    source: KnowledgeSource,
    access_control: KnowledgeAccessControl,
    data_classification: DataClassification,
    effective_at: datetime,
    expires_at: datetime | None,
    content: KnowledgeContent,
) -> None:
    if not isinstance(context, KnowledgeRequestContext):
        raise ValueError("knowledge request context is invalid")
    _require_document_id(document_id)
    if not isinstance(source, KnowledgeSource):
        raise ValueError("knowledge source is invalid")
    if not isinstance(access_control, KnowledgeAccessControl):
        raise ValueError("knowledge access control is invalid")
    if not isinstance(data_classification, DataClassification):
        raise ValueError("knowledge classification is invalid")
    effective = _utc(effective_at, "effective_at")
    if expires_at is not None and _utc(expires_at, "expires_at") <= effective:
        raise ValueError("expires_at must be after effective_at")
    if not isinstance(content, KnowledgeContent):
        raise ValueError("knowledge content is invalid")


def _require_document_id(value: object) -> None:
    import re

    if (
        not isinstance(value, str)
        or re.fullmatch(r"^doc_[A-Za-z0-9_-]{8,128}$", value) is None
    ):
        raise ValueError("document_id has an invalid format")


def _require_revision(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 2**53 - 1
    ):
        raise ValueError(f"{field_name} must be a non-negative safe integer")


def _require_optional_revision(value: object) -> None:
    if value is not None:
        _require_revision(value, "version")


def _require_sha256(value: object, field_name: str) -> None:
    import re

    if (
        not isinstance(value, str)
        or re.fullmatch(r"^sha256:[a-f0-9]{64}$", value) is None
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_text(value: object, field_name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded non-empty text")


def _utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")
