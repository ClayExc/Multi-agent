from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from flowpilot_domain import DataClassification, TaskCommand, canonical_sha256

APPLICATION_PORT_VERSION = "flowpilot.application-ports.m0.v1"
REFERENCE_PORT_VERSION = "flowpilot.reference-ports.p1.v1"
_SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ExecutionDisposition(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


class ArtifactWriteDisposition(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    command_id: str
    tenant_id: str
    task_id: str
    disposition: ExecutionDisposition
    execution_ref: str


@dataclass(frozen=True, slots=True)
class StoredCommand:
    command: TaskCommand
    accepted_at: datetime
    execution_receipt: ExecutionReceipt | None = None

    def __post_init__(self) -> None:
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("accepted_at must be timezone-aware")
        object.__setattr__(self, "accepted_at", self.accepted_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CommandAcceptance:
    command_id: str
    tenant_id: str
    task_id: str
    accepted_at: datetime
    replayed: bool
    execution_receipt: ExecutionReceipt


@dataclass(frozen=True, slots=True)
class RequestReferenceQuery:
    tenant_id: str
    task_id: str
    message_id: str
    message_ref: str
    purpose: str
    security_context_ref: str

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_identifier(
            self.task_id,
            "task_id",
            r"^task_[A-Za-z0-9_-]{8,128}$",
        )
        _require_identifier(
            self.message_id,
            "message_id",
            r"^msg_[A-Za-z0-9_-]{8,128}$",
        )
        _require_text(self.message_ref, "message_ref", maximum=512)
        _require_text(self.purpose, "purpose", maximum=256)
        _require_text(
            self.security_context_ref,
            "security_context_ref",
            maximum=512,
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "message_id": self.message_id,
            "message_ref": self.message_ref,
            "purpose": self.purpose,
            "security_context_ref": self.security_context_ref,
        }


@dataclass(frozen=True, slots=True)
class ResolvedRequestReference:
    query: RequestReferenceQuery
    observation_ref: str
    source_digest: str
    intent: str
    fields: Mapping[str, str]
    data_classification: DataClassification
    observation_digest: str

    def __post_init__(self) -> None:
        _require_text(self.observation_ref, "observation_ref", maximum=512)
        _require_sha256(self.source_digest, "source_digest")
        _require_identifier(
            self.intent,
            "intent",
            r"^[a-z][a-z0-9_]{1,63}$",
        )
        object.__setattr__(self, "fields", _freeze_fields(self.fields))
        _require_sha256(self.observation_digest, "observation_digest")

    def digest_projection(self) -> dict[str, Any]:
        return {
            "query": self.query.to_mapping(),
            "observation_ref": self.observation_ref,
            "source_digest": self.source_digest,
            "intent": self.intent,
            "fields": dict(self.fields),
            "data_classification": self.data_classification.value,
        }

    def recompute_digest(self) -> str:
        return canonical_sha256(self.digest_projection())

    def assert_digest(self) -> None:
        if self.observation_digest != self.recompute_digest():
            raise ValueError("observation_digest does not match the resolved request")


@dataclass(frozen=True, slots=True)
class RequestObservation:
    tenant_id: str
    task_id: str
    message_id: str
    observation_ref: str
    source_digest: str
    intent: str
    fields: Mapping[str, str]
    missing_fields: tuple[str, ...]
    data_classification: DataClassification

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_identifier(
            self.task_id,
            "task_id",
            r"^task_[A-Za-z0-9_-]{8,128}$",
        )
        _require_identifier(
            self.message_id,
            "message_id",
            r"^msg_[A-Za-z0-9_-]{8,128}$",
        )
        _require_text(self.observation_ref, "observation_ref", maximum=512)
        _require_sha256(self.source_digest, "source_digest")
        _require_identifier(
            self.intent,
            "intent",
            r"^[a-z][a-z0-9_]{1,63}$",
        )
        object.__setattr__(self, "fields", _freeze_fields(self.fields))
        if len(self.missing_fields) != len(set(self.missing_fields)):
            raise ValueError("missing_fields must be unique")
        for field_name in self.missing_fields:
            _require_field_name(field_name, "missing_fields")


@dataclass(frozen=True, slots=True)
class ResultCitation:
    source_ref: str
    document_version: str
    section: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_text(self.source_ref, "source_ref", maximum=512)
        _require_text(
            self.document_version,
            "document_version",
            maximum=128,
        )
        _require_text(self.section, "section", maximum=256)
        _require_sha256(self.content_hash, "content_hash")

    def to_mapping(self) -> dict[str, str]:
        return {
            "source_ref": self.source_ref,
            "document_version": self.document_version,
            "section": self.section,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ResultArtifactDraft:
    tenant_id: str
    task_id: str
    idempotency_key: str
    media_type: str
    content: str
    citations: tuple[ResultCitation, ...]
    result_digest: str

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_identifier(
            self.task_id,
            "task_id",
            r"^task_[A-Za-z0-9_-]{8,128}$",
        )
        _require_sha256(self.idempotency_key, "idempotency_key")
        if self.media_type not in {"text/plain", "text/markdown"}:
            raise ValueError("media_type is not supported")
        _require_text(self.content, "content", maximum=64 * 1024)
        if not self.citations:
            raise ValueError("citations must not be empty")
        if len(self.citations) != len(
            {citation.to_mapping()["source_ref"] for citation in self.citations}
        ):
            raise ValueError("citations must contain unique source references")
        _require_sha256(self.result_digest, "result_digest")

    def digest_projection(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "media_type": self.media_type,
            "content": self.content,
            "citations": [citation.to_mapping() for citation in self.citations],
        }

    def recompute_digest(self) -> str:
        return canonical_sha256(self.digest_projection())

    def assert_digest(self) -> None:
        if self.result_digest != self.recompute_digest():
            raise ValueError("result_digest does not match the result artifact")


@dataclass(frozen=True, slots=True)
class ResultArtifactReceipt:
    tenant_id: str
    task_id: str
    idempotency_key: str
    result_digest: str
    disposition: ArtifactWriteDisposition
    result_ref: str | None

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_identifier(
            self.task_id,
            "task_id",
            r"^task_[A-Za-z0-9_-]{8,128}$",
        )
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.result_digest, "result_digest")
        if self.disposition is ArtifactWriteDisposition.CONFLICT:
            if self.result_ref is not None:
                raise ValueError("conflict receipts must not expose a result_ref")
        else:
            _require_text(self.result_ref, "result_ref", maximum=512)


def _freeze_fields(value: Mapping[str, str]) -> Mapping[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        _require_field_name(key, "fields")
        _require_text(item, f"fields.{key}", maximum=256)
        result[key] = item
    return MappingProxyType(result)


def _require_field_name(value: object, field: str) -> None:
    if not isinstance(value, str) or _FIELD_NAME_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} contains an invalid field name")


def _require_text(value: object, field: str, *, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field} must be a bounded non-empty string")


def _require_identifier(value: object, field: str, pattern: str) -> None:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(f"{field} has an invalid format")


def _require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")
