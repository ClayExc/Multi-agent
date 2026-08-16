from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

from flowpilot_application import KnowledgeRequestContext
from flowpilot_domain import (
    AclPrincipal,
    AclPrincipalType,
    DataClassification,
    SecurityContextRef,
)
from flowpilot_mcp_gateway import (
    GatewayAdapterDisposition,
    GatewayAdapterError,
    ReadbackResult,
    ReconciliationDisposition,
    ReconciliationResult,
    ToolInvocationResult,
)
from flowpilot_retrieval import (
    RetrievalError,
    RetrievalErrorCode,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
)
from flowpilot_security import (
    CapabilityHandle,
    CapabilityUse,
    ContentSurface,
    SecurityError,
    assert_content_safe,
)

from .server import KNOWLEDGE_SEARCH_SCOPE, TOOL_NAME

KNOWLEDGE_RETRIEVAL_ADAPTER_VERSION = "flowpilot.knowledge-mcp.m10.v1"
KNOWLEDGE_MCP_AUDIENCE = "mcp://flowpilot-gateway"

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_CONTENT_REF = re.compile(r"^knowledge-content://[a-f0-9]{64}$")
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}
_ACL_TYPES = {
    "group": AclPrincipalType.GROUP,
    "role": AclPrincipalType.ROLE,
    "service": AclPrincipalType.SERVICE,
}


class KnowledgeRetrievalPort(Protocol):
    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...


class RetrievalKnowledgeMcpAdapter:
    """M10 read boundary over the authorized Retrieval Port.

    The public ``invoke`` method deliberately fails closed. Production Gateway
    composition must use ``invoke_with_trusted_context`` after resolving and
    verifying the public SecurityContextRef.
    """

    def __init__(
        self,
        retrieval: KnowledgeRetrievalPort,
        *,
        expected_audience: str = KNOWLEDGE_MCP_AUDIENCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not expected_audience or len(expected_audience) > 256:
            raise ValueError("knowledge MCP audience is invalid")
        self._retrieval = retrieval
        self._expected_audience = expected_audience
        self._clock = clock or (lambda: datetime.now(UTC))
        self.invocation_count = 0
        self.retrieval_count = 0
        self.returned_record_count = 0
        self.direct_invocation_rejection_count = 0

    async def invoke(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        del arguments, capability, idempotency_key
        self.direct_invocation_rejection_count += 1
        raise _adapter_error(
            "KNOWLEDGE_ACCESS_DENIED",
            "knowledge retrieval requires a Gateway-verified security context",
        )

    async def invoke_with_trusted_context(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        security_context: SecurityContextRef,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        del idempotency_key
        self.invocation_count += 1
        now = _utc(self._clock())
        action_ceiling = self._verify_binding(
            capability=capability,
            security_context=security_context,
            now=now,
        )
        query, limit = _query_and_limit(arguments)
        principals = _trusted_principals(capability)
        context = KnowledgeRequestContext(
            tenant_id=security_context.tenant_id,
            purpose=security_context.purpose,
            security_context=security_context,
        )
        try:
            request = RetrievalRequest(
                context=context,
                principals=principals,
                action_classification_ceiling=action_ceiling,
                query_text=query,
                observed_at=now,
                candidate_limit=min(100, max(limit, limit * 5)),
                result_limit=limit,
            )
            self.retrieval_count += 1
            result = await self._retrieval.retrieve(request)
        except RetrievalError as exc:
            raise _map_retrieval_error(exc.code) from None
        except GatewayAdapterError:
            raise
        except Exception:
            raise _adapter_error(
                "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
                "knowledge retrieval is unavailable",
                disposition=GatewayAdapterDisposition.NOT_SENT,
            ) from None
        records = self._safe_records(
            result,
            tenant_id=security_context.tenant_id,
            action_ceiling=action_ceiling,
            limit=limit,
        )
        self.returned_record_count += len(records)
        return ToolInvocationResult(
            data={"records": records, "returned_count": len(records)}
        )

    def _verify_binding(
        self,
        *,
        capability: CapabilityHandle,
        security_context: SecurityContextRef,
        now: datetime,
    ) -> DataClassification:
        try:
            action_ceiling = DataClassification(
                capability.data_classification_ceiling
            )
        except ValueError:
            raise _adapter_error(
                "KNOWLEDGE_ACCESS_DENIED",
                "knowledge capability classification was denied",
            ) from None
        if (
            capability.use is not CapabilityUse.INVOKE
            or capability.audience != self._expected_audience
            or capability.tool_name != TOOL_NAME
            or KNOWLEDGE_SEARCH_SCOPE not in capability.scopes
            or capability.tenant_id != security_context.tenant_id
            or capability.subject_id != security_context.subject_id
            or capability.purpose != security_context.purpose
            or capability.context_hash != security_context.context_hash
            or now < capability.issued_at
            or now >= capability.expires_at
            or now < security_context.issued_at
            or now >= security_context.expires_at
            or capability.expires_at > security_context.expires_at
            or _CLASSIFICATION_RANK[action_ceiling]
            > _CLASSIFICATION_RANK[
                security_context.data_classification_ceiling
            ]
        ):
            raise _adapter_error(
                "KNOWLEDGE_ACCESS_DENIED",
                "knowledge access capability was denied",
            )
        return action_ceiling

    def _safe_records(
        self,
        result: object,
        *,
        tenant_id: str,
        action_ceiling: DataClassification,
        limit: int,
    ) -> list[dict[str, str]]:
        if not isinstance(result, RetrievalResult) or len(result.hits) > limit:
            raise _adapter_error(
                "KNOWLEDGE_REFERENCE_REJECTED",
                "knowledge retrieval result violated the pinned protocol",
            )
        records: list[dict[str, str]] = []
        seen: set[tuple[str, int, str, str]] = set()
        for hit in result.hits:
            record, identity = _safe_record(
                hit,
                tenant_id=tenant_id,
                action_ceiling=action_ceiling,
            )
            if identity in seen:
                raise _adapter_error(
                    "KNOWLEDGE_REFERENCE_REJECTED",
                    "knowledge retrieval returned a duplicate citation",
                )
            seen.add(identity)
            try:
                assert_content_safe(
                    record,
                    surface=ContentSurface.MCP_CONTENT,
                    field="knowledge_result",
                )
            except SecurityError:
                raise _adapter_error(
                    "KNOWLEDGE_CONTENT_REJECTED",
                    "knowledge content did not pass the content safety boundary",
                ) from None
            records.append(record)
        return records

    async def readback(
        self,
        *,
        arguments: Mapping[str, Any],
        invocation: ToolInvocationResult,
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReadbackResult:
        del arguments, invocation, capability, idempotency_key
        raise RuntimeError("read-only Knowledge MCP does not support readback")

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


def _query_and_limit(arguments: Mapping[str, Any]) -> tuple[str, int]:
    query_value = arguments.get("query")
    limit_value = arguments.get("limit")
    if (
        not isinstance(query_value, str)
        or not query_value
        or len(query_value) > 256
        or any(ord(character) < 32 for character in query_value)
        or isinstance(limit_value, bool)
        or not isinstance(limit_value, int)
        or not 1 <= limit_value <= 20
    ):
        raise _adapter_error(
            "KNOWLEDGE_QUERY_REJECTED",
            "knowledge query did not pass deterministic validation",
        )
    try:
        assert_content_safe(
            query_value,
            surface=ContentSurface.TOOL_ARGUMENTS,
            field="knowledge_query",
        )
    except SecurityError:
        raise _adapter_error(
            "KNOWLEDGE_QUERY_REJECTED",
            "knowledge query did not pass the content safety boundary",
        ) from None
    normalized = " ".join(query_value.split())
    if not normalized:
        raise _adapter_error(
            "KNOWLEDGE_QUERY_REJECTED",
            "knowledge query did not pass deterministic validation",
        )
    return normalized, limit_value


def _trusted_principals(
    capability: CapabilityHandle,
) -> tuple[AclPrincipal, ...]:
    principals = {
        AclPrincipal(AclPrincipalType.SUBJECT, capability.subject_id)
    }
    for value in capability.subject_acl:
        prefix, separator, principal_id = value.partition(":")
        if not separator:
            principals.add(AclPrincipal(AclPrincipalType.ROLE, value))
            continue
        if prefix == "subject":
            if principal_id != capability.subject_id:
                raise _adapter_error(
                    "KNOWLEDGE_ACCESS_DENIED",
                    "knowledge subject ACL binding was denied",
                )
            continue
        principal_type = _ACL_TYPES.get(prefix)
        if principal_type is None or not principal_id:
            raise _adapter_error(
                "KNOWLEDGE_ACCESS_DENIED",
                "knowledge ACL principal type was denied",
            )
        principals.add(AclPrincipal(principal_type, principal_id))
    return tuple(sorted(principals))


def _safe_record(
    hit: object,
    *,
    tenant_id: str,
    action_ceiling: DataClassification,
) -> tuple[dict[str, str], tuple[str, int, str, str]]:
    if not isinstance(hit, RetrievalHit):
        raise _adapter_error(
            "KNOWLEDGE_REFERENCE_REJECTED",
            "knowledge retrieval returned an invalid hit",
        )
    citation = hit.citation
    excerpt = hit.content_excerpt
    if (
        citation.tenant_id != tenant_id
        or not _CONTENT_REF.fullmatch(hit.content_ref)
        or not _SHA256.fullmatch(citation.content_hash)
        or not isinstance(hit.data_classification, DataClassification)
        or _CLASSIFICATION_RANK[hit.data_classification]
        > _CLASSIFICATION_RANK[action_ceiling]
        or not isinstance(excerpt, str)
        or not excerpt
        or len(excerpt) > 2048
        or any(
            ord(character) < 32 and character not in "\n\r\t"
            for character in excerpt
        )
    ):
        raise _adapter_error(
            "KNOWLEDGE_REFERENCE_REJECTED",
            "knowledge retrieval hit binding was rejected",
        )
    source_ref = (
        f"knowledge://{quote(citation.tenant_id, safe='')}/"
        f"{quote(citation.document_id, safe='')}/"
        f"{citation.document_version}#{quote(citation.section_id, safe='')}"
    )
    record = {
        "source_ref": source_ref,
        "document_version": str(citation.document_version),
        "section": citation.section_id,
        "redacted_summary": excerpt,
        "content_hash": citation.content_hash,
        "classification": hit.data_classification.value,
    }
    identity = (
        citation.document_id,
        citation.document_version,
        citation.section_id,
        citation.content_hash,
    )
    return record, identity


def _map_retrieval_error(code: RetrievalErrorCode) -> GatewayAdapterError:
    if code in {
        RetrievalErrorCode.REQUEST_INVALID,
        RetrievalErrorCode.SECURITY_BINDING_MISMATCH,
        RetrievalErrorCode.SECURITY_CONTEXT_UNAVAILABLE,
    }:
        return _adapter_error(
            "KNOWLEDGE_ACCESS_DENIED",
            "knowledge retrieval security binding was denied",
        )
    if code in {
        RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION,
        RetrievalErrorCode.REFERENCE_REVALIDATION_FAILED,
    }:
        return _adapter_error(
            "KNOWLEDGE_REFERENCE_REJECTED",
            "knowledge retrieval reference verification failed",
        )
    return _adapter_error(
        "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
        "knowledge retrieval is unavailable",
        disposition=GatewayAdapterDisposition.NOT_SENT,
    )


def _adapter_error(
    code: str,
    message: str,
    *,
    disposition: GatewayAdapterDisposition = GatewayAdapterDisposition.REJECTED,
) -> GatewayAdapterError:
    return GatewayAdapterError(disposition, code, message)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise _adapter_error(
            "KNOWLEDGE_ACCESS_DENIED",
            "knowledge clock did not provide a trusted UTC instant",
        )
    return value.astimezone(UTC)
