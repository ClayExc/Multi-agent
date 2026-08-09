from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from flowpilot_domain import (
    DataClassification,
    ReleaseRef,
    TaskCommand,
    canonical_sha256,
)

from .task_events import (
    TASK_EVENT_PAYLOAD_RULES,
    TASK_EVENT_PRODUCERS,
    assert_task_event_content_safe,
    validate_task_event_payload,
    validate_task_event_ref,
)

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
class TaskInitializationConfig:
    """Trusted composition values for a new Task projection."""

    release: ReleaseRef
    data_classification: DataClassification

    def __post_init__(self) -> None:
        if not isinstance(self.release, ReleaseRef):
            raise TypeError("release must be a ReleaseRef")
        if not isinstance(self.data_classification, DataClassification):
            raise TypeError("data_classification must be a DataClassification")


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
    result_ref: str | None
    disposition: ArtifactWriteDisposition

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_identifier(self.task_id, "task_id", r"^task_[A-Za-z0-9_-]{8,128}$")
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.result_digest, "result_digest")
        if self.disposition is ArtifactWriteDisposition.CONFLICT:
            if self.result_ref is not None:
                raise ValueError("conflict receipts must not expose a result_ref")
        else:
            _require_text(self.result_ref, "result_ref", maximum=512)


@dataclass(frozen=True, slots=True)
class OutboxEventView:
    """Tenant-scoped outbox event projection used by the SSE subscription."""

    event_id: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    occurred_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_text(self.event_id, "event_id", maximum=256)
        _require_text(self.aggregate_type, "aggregate_type", maximum=256)
        _require_text(self.aggregate_id, "aggregate_id", maximum=256)
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("outbox sequence must be positive")
        _require_text(self.event_type, "event_type", maximum=256)
        payload = _freeze_json(self.payload, "payload")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at, "occurred_at"))
        object.__setattr__(
            self, "available_at", _utc(self.available_at, "available_at")
        )


_TASK_EVENT_TYPES = frozenset(TASK_EVENT_PAYLOAD_RULES)
_CLASSIFICATIONS = frozenset(
    {"public", "internal", "confidential", "restricted"}
)
_RUN_ID_PATTERN = re.compile(r"^run_[A-Za-z0-9_-]{8,128}$")


@dataclass(frozen=True, slots=True)
class TaskEventEnvelope:
    """Full task-event.v1 envelope delivered to the SSE transport."""

    event_id: str
    event_type: str
    tenant_id: str
    task_id: str
    thread_id: str
    task_version: int
    sequence: int
    trace_id: str
    run_id: str | None
    producer: str
    producer_principal_ref: str
    correlation_id: str
    causation_id: str | None
    data_classification: str
    payload: Mapping[str, Any]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        object.__setattr__(self, "payload", _freeze_json(self.payload, "payload"))
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at, "occurred_at"))
        self.assert_valid()

    def assert_valid(self) -> None:
        """Revalidate the complete envelope before any trust-boundary use."""

        _require_identifier(self.event_id, "event_id", r"^evt_[A-Za-z0-9_-]{8,128}$")
        if (
            not isinstance(self.event_type, str)
            or self.event_type not in _TASK_EVENT_TYPES
        ):
            raise ValueError(f"{self.event_type} is not a task-event.v1 type")
        _require_text(self.tenant_id, "tenant_id", maximum=128)
        _require_identifier(self.task_id, "task_id", r"^task_[A-Za-z0-9_-]{8,128}$")
        _require_identifier(
            self.thread_id, "thread_id", r"^thread_[A-Za-z0-9_-]{8,128}$"
        )
        if (
            isinstance(self.task_version, bool)
            or not isinstance(self.task_version, int)
            or self.task_version < 0
        ):
            raise ValueError("task_version must be a non-negative integer")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if not isinstance(self.trace_id, str) or not 16 <= len(self.trace_id) <= 128:
            raise ValueError("trace_id must be a bounded string")
        if self.run_id is not None and (
            not isinstance(self.run_id, str)
            or _RUN_ID_PATTERN.fullmatch(self.run_id) is None
        ):
            raise ValueError("run_id has an invalid format")
        if (
            not isinstance(self.producer, str)
            or self.producer not in TASK_EVENT_PRODUCERS
        ):
            raise ValueError(f"{self.producer} is not a task-event.v1 producer")
        if self.producer != "approval_service" and self.run_id is None:
            raise ValueError("run_id is required for this task-event.v1 producer")
        _require_text(
            self.producer_principal_ref, "producer_principal_ref", maximum=512
        )
        validate_task_event_ref(
            self.producer_principal_ref, "producer_principal_ref"
        )
        _require_text(self.correlation_id, "correlation_id", maximum=128)
        if self.causation_id is not None and (
            not isinstance(self.causation_id, str) or len(self.causation_id) > 128
        ):
            raise ValueError("causation_id must be a bounded string or null")
        if (
            not isinstance(self.data_classification, str)
            or self.data_classification not in _CLASSIFICATIONS
        ):
            raise ValueError(
                f"{self.data_classification} is not a task-event classification"
            )
        validate_task_event_payload(self.event_type, self.producer, self.payload)
        if not isinstance(self.occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        occurred_at = _utc(self.occurred_at, "occurred_at")
        assert_task_event_content_safe(
            {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "tenant_id": self.tenant_id,
                "task_id": self.task_id,
                "thread_id": self.thread_id,
                "trace_id": self.trace_id,
                "run_id": self.run_id,
                "producer": self.producer,
                "producer_principal_ref": self.producer_principal_ref,
                "correlation_id": self.correlation_id,
                "causation_id": self.causation_id,
                "data_classification": self.data_classification,
                "occurred_at": _format_utc(occurred_at),
            },
            "envelope",
        )

    def to_mapping(self) -> dict[str, Any]:
        self.assert_valid()
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "task_version": self.task_version,
            "sequence": self.sequence,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "producer": self.producer,
            "producer_principal_ref": self.producer_principal_ref,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "data_classification": self.data_classification,
            "payload": _json_wire_value(self.payload),
            "occurred_at": _format_utc(self.occurred_at),
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_mapping(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


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


def _freeze_json(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field} keys must be strings")
        frozen[key] = _freeze_json_value(item, f"{field}.{key}")
    return MappingProxyType(frozen)


def _freeze_json_value(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return _freeze_json(value, field)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(
            _freeze_json_value(item, f"{field}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{field} must contain JSON values")


def _json_wire_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_wire_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_wire_value(item) for item in value]
    return value


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")
