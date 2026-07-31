from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flowpilot_mcp_gateway import (
    GatewayAdapterDisposition,
    GatewayAdapterError,
    ReadbackResult,
    ReconciliationDisposition,
    ReconciliationResult,
    ToolInvocationResult,
)
from flowpilot_security import CapabilityHandle
from flowpilot_tool_contracts import ToolContract

TOOL_NAME = "knowledge.search.v1"
KNOWLEDGE_MCP_VERSION = "flowpilot.knowledge-mcp.p1.v1"
KNOWLEDGE_SEARCH_SCOPE = "knowledge.search"
LEGACY_KNOWLEDGE_SCHEMA_PIN = (
    "sha256:fa39a6eb55d2d2bf68174a47dcb00d63a58e771e7ba5e3781cde4d716a319c04"
)

_SHA256_PATTERN = r"^sha256:[a-f0-9]{64}$"
_CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}
_QUERY_ATTACK_PATTERNS = (
    re.compile(r"(?i)\bignore\s+(?:all|any|previous|prior)\b"),
    re.compile(r"(?i)\b(?:system|developer)\s+(?:prompt|message)\b"),
    re.compile(r"(?i)\bbypass\s+(?:acl|policy|authorization|tenant)\b"),
    re.compile(r"(?i)\breveal\s+(?:acl|password|secret|token)\b"),
    re.compile(r"(?i)\bcross[-\s]?tenant\b"),
    re.compile(r"(?i)\bacl_subjects\b"),
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query", "limit"],
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 256},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["records", "returned_count"],
    "properties": {
        "records": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_ref",
                    "document_version",
                    "section",
                    "redacted_summary",
                    "content_hash",
                    "classification",
                ],
                "properties": {
                    "source_ref": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 512,
                    },
                    "document_version": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                    "section": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                    },
                    "redacted_summary": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2048,
                    },
                    "content_hash": {
                        "type": "string",
                        "pattern": _SHA256_PATTERN,
                    },
                    "classification": {
                        "type": "string",
                        "enum": [
                            "public",
                            "internal",
                            "confidential",
                            "restricted",
                        ],
                    },
                },
            },
        },
        "returned_count": {"type": "integer", "minimum": 0, "maximum": 20},
    },
}

KNOWLEDGE_CONTRACT = ToolContract.create(
    name=TOOL_NAME,
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
)
KNOWLEDGE_SCHEMA_PIN = (
    "sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b"
)
if KNOWLEDGE_CONTRACT.schema_hash != KNOWLEDGE_SCHEMA_PIN:
    raise RuntimeError("knowledge.search.v1 schema drifted from its fixed pin")


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _bounded(value: str, field: str, maximum: int) -> None:
    if not value or len(value) > maximum:
        raise ValueError(f"{field} must be a bounded non-empty string")


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    tenant_id: str
    source_ref: str
    document_version: str
    section: str
    redacted_summary: str
    content_hash: str
    data_classification: str
    acl_subjects: frozenset[str]
    allowed_workload_principals: frozenset[str]
    allowed_purposes: frozenset[str]
    effective_at: datetime
    expires_at: datetime | None

    def __post_init__(self) -> None:
        for field, value, maximum in (
            ("tenant_id", self.tenant_id, 128),
            ("source_ref", self.source_ref, 512),
            ("document_version", self.document_version, 128),
            ("section", self.section, 256),
            ("redacted_summary", self.redacted_summary, 2048),
        ):
            _bounded(value, field, maximum)
        if not self.source_ref.startswith(f"knowledge://{self.tenant_id}/"):
            raise ValueError("source_ref does not match its trusted tenant")
        if re.fullmatch(_SHA256_PATTERN, self.content_hash) is None:
            raise ValueError("content_hash must be a lowercase sha256 digest")
        if self.data_classification not in _CLASSIFICATION_RANK:
            raise ValueError("data_classification is unsupported")
        if not self.acl_subjects:
            raise ValueError("knowledge ACL cannot be empty")
        if not self.allowed_workload_principals:
            raise ValueError("knowledge workload ACL cannot be empty")
        if not self.allowed_purposes:
            raise ValueError("knowledge purpose ACL cannot be empty")
        effective = _utc(self.effective_at, "effective_at")
        expires = (
            _utc(self.expires_at, "expires_at") if self.expires_at is not None else None
        )
        if expires is not None and expires <= effective:
            raise ValueError("expires_at must be after effective_at")
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "expires_at", expires)


class KnowledgeMcpAdapter:
    """Deterministic read-only adapter with pre-retrieval authorization."""

    def __init__(
        self,
        records: tuple[KnowledgeRecord, ...],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len({record.source_ref for record in records}) != len(records):
            raise ValueError("knowledge source references must be unique")
        self._records = records
        self._clock = clock or (lambda: datetime.now(UTC))
        self.invocation_count = 0
        self.authorization_filter_count = 0
        self.candidate_count = 0
        self.logical_read_count = 0
        self.unauthorized_logical_read_count = 0
        self.content_access_source_refs: list[str] = []
        self.failure: Exception | None = None

    async def invoke(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        del idempotency_key
        self.invocation_count += 1
        if self.failure is not None:
            raise self.failure
        query = _safe_query(arguments["query"])
        limit = int(arguments["limit"])
        now = _utc(self._clock(), "knowledge clock")
        self._verify_capability(capability, now)

        authorized = tuple(
            record
            for record in self._records
            if self._metadata_authorized(record, capability, now)
        )
        self.candidate_count += len(authorized)

        matches: list[dict[str, str]] = []
        for record in sorted(authorized, key=lambda item: item.source_ref):
            self.logical_read_count += 1
            self.content_access_source_refs.append(record.source_ref)
            if not self._metadata_authorized(record, capability, now, count=False):
                self.unauthorized_logical_read_count += 1
                continue
            searchable = f"{record.section}\n{record.redacted_summary}".casefold()
            if query not in searchable:
                continue
            matches.append(
                {
                    "source_ref": record.source_ref,
                    "document_version": record.document_version,
                    "section": record.section,
                    "redacted_summary": record.redacted_summary,
                    "content_hash": record.content_hash,
                    "classification": record.data_classification,
                }
            )
            if len(matches) == limit:
                break
        return ToolInvocationResult(
            data={"records": matches, "returned_count": len(matches)}
        )

    def _verify_capability(self, capability: CapabilityHandle, now: datetime) -> None:
        if (
            KNOWLEDGE_SEARCH_SCOPE not in capability.scopes
            or not capability.tenant_id
            or not capability.subject_id
            or not capability.subject_acl
            or not capability.workload_principal_ref
            or not capability.purpose
            or capability.data_classification_ceiling not in _CLASSIFICATION_RANK
            or now < capability.issued_at
            or now >= capability.expires_at
        ):
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "KNOWLEDGE_ACCESS_DENIED",
                "knowledge access capability was denied",
            )

    def _metadata_authorized(
        self,
        record: KnowledgeRecord,
        capability: CapabilityHandle,
        now: datetime,
        *,
        count: bool = True,
    ) -> bool:
        if count:
            self.authorization_filter_count += 1
        return (
            record.tenant_id == capability.tenant_id
            and capability.purpose in record.allowed_purposes
            and (
                capability.workload_principal_ref in record.allowed_workload_principals
            )
            and bool(record.acl_subjects & capability.subject_acl)
            and _CLASSIFICATION_RANK[record.data_classification]
            <= _CLASSIFICATION_RANK[capability.data_classification_ceiling]
            and record.effective_at <= now
            and (record.expires_at is None or now < record.expires_at)
        )

    async def readback(
        self,
        *,
        arguments: Mapping[str, Any],
        invocation: ToolInvocationResult,
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReadbackResult:
        del arguments, invocation, capability, idempotency_key
        raise RuntimeError("read-only MCP does not support write readback")

    async def reconcile(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReconciliationResult:
        del arguments, capability, idempotency_key
        return ReconciliationResult(
            disposition=ReconciliationDisposition.UNKNOWN,
            data=None,
            evidence_ref=None,
            observed_ref=None,
            method="manual",
        )


def _safe_query(value: object) -> str:
    if not isinstance(value, str):
        raise GatewayAdapterError(
            GatewayAdapterDisposition.REJECTED,
            "KNOWLEDGE_QUERY_REJECTED",
            "knowledge query did not pass deterministic validation",
        )
    normalized = " ".join(value.split()).casefold()
    if (
        not normalized
        or any(ord(character) < 32 for character in value)
        or any(pattern.search(normalized) for pattern in _QUERY_ATTACK_PATTERNS)
    ):
        raise GatewayAdapterError(
            GatewayAdapterDisposition.REJECTED,
            "KNOWLEDGE_QUERY_REJECTED",
            "knowledge query did not pass deterministic validation",
        )
    return normalized
