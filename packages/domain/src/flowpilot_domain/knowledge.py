from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Self

from .canonical import canonical_sha256
from .errors import DomainErrorCode, DomainViolation
from .primitives import (
    MAX_SAFE_INTEGER,
    ensure_utc,
    format_utc,
    require_identifier,
    require_sha256,
    require_text,
)
from .security import DataClassification

_DOCUMENT_ID_PATTERN = r"^doc_[A-Za-z0-9_-]{8,128}$"
_SECTION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
_MAX_CONTENT_BYTES = 20 * 1024 * 1024


class KnowledgeLifecycle(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    DELETED = "deleted"


class KnowledgeSourceType(StrEnum):
    FILE = "file"
    URI = "uri"
    CONNECTOR = "connector"
    MANUAL = "manual"


class AclPrincipalType(StrEnum):
    SUBJECT = "subject"
    GROUP = "group"
    ROLE = "role"
    SERVICE = "service"


@dataclass(frozen=True, slots=True, order=True)
class AclPrincipal:
    principal_type: AclPrincipalType
    principal_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal_type, AclPrincipalType):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "acl principal type is invalid",
            )
        require_text(self.principal_id, "acl.principal_id", maximum=256)

    def to_mapping(self) -> dict[str, str]:
        return {
            "principal_type": self.principal_type.value,
            "principal_id": self.principal_id,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeAccessControl:
    principals: tuple[AclPrincipal, ...]
    allowed_purposes: tuple[str, ...]
    tenant_wide: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_wide, bool):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "acl.tenant_wide must be a boolean",
            )
        if not self.principals and not self.tenant_wide:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "acl must contain a principal or explicitly allow tenant-wide access",
            )
        if len(self.principals) != len(set(self.principals)):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "acl principals must be unique",
            )
        if not self.allowed_purposes:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "acl.allowed_purposes must not be empty",
            )
        for purpose in self.allowed_purposes:
            require_text(purpose, "acl.allowed_purposes", maximum=256)
        if len(self.allowed_purposes) != len(set(self.allowed_purposes)):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "acl.allowed_purposes must be unique",
            )
        object.__setattr__(self, "principals", tuple(sorted(self.principals)))
        object.__setattr__(
            self, "allowed_purposes", tuple(sorted(self.allowed_purposes))
        )

    def allows(
        self,
        principals: tuple[AclPrincipal, ...],
        purpose: str,
    ) -> bool:
        if purpose not in self.allowed_purposes:
            return False
        return self.tenant_wide or bool(set(self.principals).intersection(principals))

    def to_mapping(self) -> dict[str, object]:
        return {
            "principals": [item.to_mapping() for item in self.principals],
            "allowed_purposes": list(self.allowed_purposes),
            "tenant_wide": self.tenant_wide,
        }

    def digest(self) -> str:
        return canonical_sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    source_type: KnowledgeSourceType
    source_ref: str = field(repr=False)
    source_version: str | None = None
    source_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, KnowledgeSourceType):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "knowledge source type is invalid",
            )
        require_text(self.source_ref, "knowledge_source.source_ref", maximum=1024)
        if self.source_version is not None:
            require_text(
                self.source_version,
                "knowledge_source.source_version",
                maximum=256,
            )
        require_sha256(self.source_digest, "knowledge_source.source_digest")
        if self.source_digest != self.recompute_digest():
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_SOURCE_DIGEST_MISMATCH,
                "knowledge source digest does not match its trusted metadata",
            )

    @classmethod
    def build(
        cls,
        *,
        source_type: KnowledgeSourceType,
        source_ref: str,
        source_version: str | None = None,
    ) -> Self:
        digest = canonical_sha256(
            {
                "source_type": source_type.value,
                "source_ref": source_ref,
                "source_version": source_version,
            }
        )
        return cls(
            source_type=source_type,
            source_ref=source_ref,
            source_version=source_version,
            source_digest=digest,
        )

    def recompute_digest(self) -> str:
        return canonical_sha256(
            {
                "source_type": self.source_type.value,
                "source_ref": self.source_ref,
                "source_version": self.source_version,
            }
        )

    def safe_mapping(self) -> dict[str, str | None]:
        return {
            "source_type": self.source_type.value,
            "source_version": self.source_version,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeContent:
    text: str = field(repr=False)
    content_hash: str

    def __post_init__(self) -> None:
        normalized = normalize_knowledge_text(self.text)
        object.__setattr__(self, "text", normalized)
        require_sha256(self.content_hash, "knowledge_content.content_hash")
        if self.content_hash != knowledge_content_hash(normalized):
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_CONTENT_HASH_MISMATCH,
                "knowledge content hash does not match normalized content",
            )

    @classmethod
    def from_text(cls, text: str) -> Self:
        normalized = normalize_knowledge_text(text)
        return cls(text=normalized, content_hash=knowledge_content_hash(normalized))


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    tenant_id: str
    document_id: str
    version: int
    source: KnowledgeSource
    access_control: KnowledgeAccessControl
    data_classification: DataClassification
    effective_at: datetime
    expires_at: datetime | None
    content_ref: str
    content_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        require_text(self.tenant_id, "document_version.tenant_id", maximum=128)
        require_identifier(
            self.document_id,
            "document_version.document_id",
            _DOCUMENT_ID_PATTERN,
        )
        _require_version(self.version, "document_version.version")
        if not isinstance(self.source, KnowledgeSource):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document_version.source is invalid",
            )
        if not isinstance(self.access_control, KnowledgeAccessControl):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document_version.access_control is invalid",
            )
        if not isinstance(self.data_classification, DataClassification):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document_version.data_classification is invalid",
            )
        effective_at = ensure_utc(self.effective_at, "document_version.effective_at")
        created_at = ensure_utc(self.created_at, "document_version.created_at")
        expires_at = (
            None
            if self.expires_at is None
            else ensure_utc(self.expires_at, "document_version.expires_at")
        )
        if expires_at is not None and expires_at <= effective_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document version must expire after it becomes effective",
            )
        require_text(self.content_ref, "document_version.content_ref", maximum=512)
        require_sha256(self.content_hash, "document_version.content_hash")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "created_at", created_at)

    def is_effective(self, now: datetime) -> bool:
        observed_at = ensure_utc(now, "knowledge_query.now")
        return self.effective_at <= observed_at and (
            self.expires_at is None or observed_at < self.expires_at
        )

    def metadata_digest(self) -> str:
        return canonical_sha256(
            {
                "tenant_id": self.tenant_id,
                "document_id": self.document_id,
                "version": self.version,
                "source": self.source.safe_mapping(),
                "acl_digest": self.access_control.digest(),
                "data_classification": self.data_classification.value,
                "effective_at": format_utc(self.effective_at),
                "expires_at": (
                    None if self.expires_at is None else format_utc(self.expires_at)
                ),
                "content_ref": self.content_ref,
                "content_hash": self.content_hash,
                "created_at": format_utc(self.created_at),
            }
        )

    def citation(self, section_id: str) -> StableCitation:
        return StableCitation(
            tenant_id=self.tenant_id,
            document_id=self.document_id,
            document_version=self.version,
            section_id=section_id,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    tenant_id: str
    document_id: str
    revision: int
    current_version: int
    lifecycle: KnowledgeLifecycle
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        require_text(self.tenant_id, "knowledge_document.tenant_id", maximum=128)
        require_identifier(
            self.document_id,
            "knowledge_document.document_id",
            _DOCUMENT_ID_PATTERN,
        )
        _require_version(self.revision, "knowledge_document.revision")
        _require_version(self.current_version, "knowledge_document.current_version")
        if not isinstance(self.lifecycle, KnowledgeLifecycle):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "knowledge document lifecycle is invalid",
            )
        created_at = ensure_utc(self.created_at, "knowledge_document.created_at")
        updated_at = ensure_utc(self.updated_at, "knowledge_document.updated_at")
        retired_at = (
            None
            if self.retired_at is None
            else ensure_utc(self.retired_at, "knowledge_document.retired_at")
        )
        deleted_at = (
            None
            if self.deleted_at is None
            else ensure_utc(self.deleted_at, "knowledge_document.deleted_at")
        )
        if updated_at < created_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "knowledge document update precedes creation",
            )
        if self.lifecycle is KnowledgeLifecycle.ACTIVE:
            if retired_at is not None or deleted_at is not None:
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    "active knowledge document contains a terminal timestamp",
                )
        elif self.lifecycle is KnowledgeLifecycle.RETIRED:
            if retired_at is None or deleted_at is not None:
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    "retired knowledge document timestamps are invalid",
                )
        elif deleted_at is None:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "deleted knowledge document requires deleted_at",
            )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "retired_at", retired_at)
        object.__setattr__(self, "deleted_at", deleted_at)

    @classmethod
    def start(cls, version: DocumentVersion) -> Self:
        if version.version != 0:
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_VERSION_CONFLICT,
                "initial document version must be zero",
            )
        return cls(
            tenant_id=version.tenant_id,
            document_id=version.document_id,
            revision=0,
            current_version=0,
            lifecycle=KnowledgeLifecycle.ACTIVE,
            created_at=version.created_at,
            updated_at=version.created_at,
        )

    def advance(
        self,
        version: DocumentVersion,
        *,
        expected_revision: int,
        now: datetime,
    ) -> Self:
        self._assert_active(expected_revision)
        if (
            version.tenant_id != self.tenant_id
            or version.document_id != self.document_id
            or version.version != self.current_version + 1
        ):
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_VERSION_CONFLICT,
                "next document version does not follow the current version",
            )
        observed_at = ensure_utc(now, "knowledge_document.update_time")
        if version.created_at != observed_at or observed_at < self.updated_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document version timestamp does not match the update",
            )
        return replace(
            self,
            revision=self.revision + 1,
            current_version=version.version,
            updated_at=observed_at,
        )

    def retire(self, *, expected_revision: int, now: datetime) -> Self:
        self._assert_active(expected_revision)
        observed_at = ensure_utc(now, "knowledge_document.retired_at")
        if observed_at < self.updated_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document retirement precedes its latest update",
            )
        return replace(
            self,
            revision=self.revision + 1,
            lifecycle=KnowledgeLifecycle.RETIRED,
            updated_at=observed_at,
            retired_at=observed_at,
        )

    def delete(self, *, expected_revision: int, now: datetime) -> Self:
        self._assert_revision(expected_revision)
        if self.lifecycle is KnowledgeLifecycle.DELETED:
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_INVALID_STATE,
                "knowledge document is already deleted",
            )
        observed_at = ensure_utc(now, "knowledge_document.deleted_at")
        if observed_at < self.updated_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "document deletion precedes its latest update",
            )
        return replace(
            self,
            revision=self.revision + 1,
            lifecycle=KnowledgeLifecycle.DELETED,
            updated_at=observed_at,
            deleted_at=observed_at,
        )

    def _assert_active(self, expected_revision: int) -> None:
        self._assert_revision(expected_revision)
        if self.lifecycle is not KnowledgeLifecycle.ACTIVE:
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_INVALID_STATE,
                "knowledge document is not active",
            )

    def _assert_revision(self, expected_revision: int) -> None:
        _require_version(expected_revision, "expected_revision")
        if expected_revision != self.revision:
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_VERSION_CONFLICT,
                "knowledge document revision does not match expected_revision",
            )


@dataclass(frozen=True, slots=True)
class StableCitation:
    tenant_id: str
    document_id: str
    document_version: int
    section_id: str
    content_hash: str

    def __post_init__(self) -> None:
        require_text(self.tenant_id, "citation.tenant_id", maximum=128)
        require_identifier(
            self.document_id, "citation.document_id", _DOCUMENT_ID_PATTERN
        )
        _require_version(self.document_version, "citation.document_version")
        require_identifier(self.section_id, "citation.section_id", _SECTION_ID_PATTERN)
        require_sha256(self.content_hash, "citation.content_hash")

    def assert_matches(self, version: DocumentVersion) -> None:
        if (
            self.tenant_id != version.tenant_id
            or self.document_id != version.document_id
            or self.document_version != version.version
            or self.content_hash != version.content_hash
        ):
            raise DomainViolation(
                DomainErrorCode.KNOWLEDGE_REFERENCE_MISMATCH,
                "stable citation does not match the exact document version",
            )

    def to_mapping(self) -> dict[str, str | int]:
        return {
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,
            "document_version": self.document_version,
            "section_id": self.section_id,
            "content_hash": self.content_hash,
        }


def normalize_knowledge_text(text: str) -> str:
    if not isinstance(text, str):
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            "knowledge content must be text",
        )
    normalized = (
        unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    )
    if not normalized or "\x00" in normalized:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            "knowledge content must be non-empty text without NUL bytes",
        )
    if len(normalized.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            "knowledge content exceeds the maximum byte size",
        )
    return normalized


def knowledge_content_hash(text: str) -> str:
    normalized = normalize_knowledge_text(text)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_version(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SAFE_INTEGER
    ):
        raise DomainViolation(
            DomainErrorCode.CONTRACT_VIOLATION,
            f"{field_name} must be a non-negative safe integer",
        )
