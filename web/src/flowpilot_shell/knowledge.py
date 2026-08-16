"""Closed, display-safe views for the Knowledge API.

The Web shell deliberately models only metadata returned by the authoritative
API.  Source references, content bodies, ACL principals, vectors and tenant or
role fields are not part of these views and therefore cannot be rendered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import ShellContractError

_DOCUMENT_ID = re.compile(r"^doc_[A-Za-z0-9_-]{8,128}$")
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})
_LIFECYCLES = frozenset({"active", "retired", "deleted"})
_SOURCE_TYPES = frozenset({"file", "uri", "connector", "manual"})
_INDEX_STATES = frozenset({"missing", "pending", "ready", "failed", "stale", "removed"})


class KnowledgeConflictError(ShellContractError):
    """The authoritative revision changed before a requested mutation."""


class KnowledgeInputError(ValueError):
    """The API rejected a syntactically valid browser mutation request."""


def parse_document_id(value: str) -> str:
    if _DOCUMENT_ID.fullmatch(value) is None:
        raise ShellContractError("knowledge document id is invalid")
    return value


def parse_document_version(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if not value.isascii() or not value.isdecimal():
        raise ShellContractError("knowledge document version is invalid")
    parsed = int(value)
    if parsed > 2**53 - 1:
        raise ShellContractError("knowledge document version is invalid")
    return parsed


def parse_expected_hash(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if _SHA256.fullmatch(value) is None:
        raise ShellContractError("knowledge citation hash is invalid")
    return value


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentView:
    document_id: str
    revision: int
    current_version: int
    lifecycle: str
    document_version: int
    source_type: str
    source_version: str | None
    source_digest: str
    acl_digest: str
    data_classification: str
    effective_at: str
    expires_at: str | None
    content_hash: str
    created_at: str
    updated_at: str

    @classmethod
    def from_mapping(cls, value: object) -> KnowledgeDocumentView:
        mapping = _mapping(value, "knowledge document")
        _exact(
            mapping,
            {
                "document_id",
                "revision",
                "current_version",
                "lifecycle",
                "document_version",
                "source_type",
                "source_version",
                "source_digest",
                "acl_digest",
                "data_classification",
                "effective_at",
                "expires_at",
                "content_hash",
                "created_at",
                "updated_at",
            },
            "knowledge document",
        )
        return cls(
            document_id=parse_document_id(
                _text(mapping["document_id"], "document_id", 133)
            ),
            revision=_version(mapping["revision"], "revision"),
            current_version=_version(mapping["current_version"], "current_version"),
            lifecycle=_choice(mapping["lifecycle"], _LIFECYCLES, "lifecycle"),
            document_version=_version(mapping["document_version"], "document_version"),
            source_type=_choice(mapping["source_type"], _SOURCE_TYPES, "source_type"),
            source_version=_optional_text(
                mapping["source_version"], "source_version", 256
            ),
            source_digest=_digest(mapping["source_digest"], "source_digest"),
            acl_digest=_digest(mapping["acl_digest"], "acl_digest"),
            data_classification=_choice(
                mapping["data_classification"], _CLASSIFICATIONS, "data_classification"
            ),
            effective_at=_timestamp(mapping["effective_at"], "effective_at"),
            expires_at=_optional_timestamp(mapping["expires_at"], "expires_at"),
            content_hash=_digest(mapping["content_hash"], "content_hash"),
            created_at=_timestamp(mapping["created_at"], "created_at"),
            updated_at=_timestamp(mapping["updated_at"], "updated_at"),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeDiagnosticView:
    document_id: str
    document_version: int
    document_revision: int
    content_hash: str
    index_state: str
    last_job_id: str | None
    indexed_at: str | None
    failure_code: str | None

    @classmethod
    def from_mapping(cls, value: object) -> KnowledgeDiagnosticView:
        mapping = _mapping(value, "knowledge diagnostic")
        _exact(
            mapping,
            {
                "document_id",
                "document_version",
                "document_revision",
                "content_hash",
                "index_state",
                "last_job_id",
                "indexed_at",
                "failure_code",
            },
            "knowledge diagnostic",
        )
        return cls(
            document_id=parse_document_id(
                _text(mapping["document_id"], "document_id", 133)
            ),
            document_version=_version(mapping["document_version"], "document_version"),
            document_revision=_version(
                mapping["document_revision"], "document_revision"
            ),
            content_hash=_digest(mapping["content_hash"], "content_hash"),
            index_state=_choice(mapping["index_state"], _INDEX_STATES, "index_state"),
            last_job_id=_optional_pattern(mapping["last_job_id"], "last_job_id"),
            indexed_at=_optional_timestamp(mapping["indexed_at"], "indexed_at"),
            failure_code=_optional_pattern(
                mapping["failure_code"], "failure_code", maximum=128
            ),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeOperationReceiptView:
    document_id: str
    operation: str
    revision: int
    document_version: int
    disposition: str
    event_id: str
    index_job_id: str

    @classmethod
    def from_mapping(cls, value: object) -> KnowledgeOperationReceiptView:
        mapping = _mapping(value, "knowledge operation receipt")
        _exact(
            mapping,
            {
                "document_id",
                "operation",
                "revision",
                "document_version",
                "disposition",
                "event_id",
                "index_job_id",
            },
            "knowledge operation receipt",
        )
        return cls(
            document_id=parse_document_id(
                _text(mapping["document_id"], "document_id", 133)
            ),
            operation=_choice(
                mapping["operation"],
                frozenset({"import", "update", "retire", "delete", "rebuild"}),
                "operation",
            ),
            revision=_version(mapping["revision"], "revision"),
            document_version=_version(mapping["document_version"], "document_version"),
            disposition=_choice(
                mapping["disposition"],
                frozenset({"applied", "duplicate"}),
                "disposition",
            ),
            event_id=_pattern(mapping["event_id"], "event_id"),
            index_job_id=_pattern(mapping["index_job_id"], "index_job_id"),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshot:
    documents: tuple[KnowledgeDocumentView, ...]
    selected: KnowledgeDocumentView | None = None
    diagnostic: KnowledgeDiagnosticView | None = None
    expected_hash: str | None = None

    @property
    def citation_status(self) -> str | None:
        if self.selected is None or self.expected_hash is None:
            return None
        return (
            "verified" if self.selected.content_hash == self.expected_hash else "drift"
        )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ShellContractError(f"{label} must be an object")
    return dict(value)


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise ShellContractError(f"{label} fields are invalid")


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ShellContractError(f"{label} is invalid")
    return value


def _optional_text(value: object, label: str, maximum: int) -> str | None:
    return None if value is None else _text(value, label, maximum)


def _version(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 2**53 - 1
    ):
        raise ShellContractError(f"{label} is invalid")
    return value


def _choice(value: object, choices: frozenset[str], label: str) -> str:
    text = _text(value, label, 128)
    if text not in choices:
        raise ShellContractError(f"{label} is invalid")
    return text


def _digest(value: object, label: str) -> str:
    text = _text(value, label, 71)
    if _SHA256.fullmatch(text) is None:
        raise ShellContractError(f"{label} is invalid")
    return text


def _pattern(value: object, label: str, *, maximum: int = 256) -> str:
    text = _text(value, label, maximum)
    if _SAFE_ID.fullmatch(text) is None:
        raise ShellContractError(f"{label} is invalid")
    return text


def _optional_pattern(value: object, label: str, *, maximum: int = 256) -> str | None:
    return None if value is None else _pattern(value, label, maximum=maximum)


def _timestamp(value: object, label: str) -> str:
    text = _text(value, label, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShellContractError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShellContractError(f"{label} is invalid")
    return text


def _optional_timestamp(value: object, label: str) -> str | None:
    return None if value is None else _timestamp(value, label)
