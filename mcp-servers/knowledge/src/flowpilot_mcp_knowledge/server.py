from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from flowpilot_mcp_gateway import (
    ReadbackResult,
    ReconciliationDisposition,
    ReconciliationResult,
    ToolInvocationResult,
)
from flowpilot_security import CapabilityHandle
from flowpilot_tool_contracts import ToolContract

TOOL_NAME = "knowledge.search.v1"
KNOWLEDGE_MCP_VERSION = "flowpilot.knowledge-mcp.m0.v1"

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
                "required": ["record_id", "title", "summary"],
                "properties": {
                    "record_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                    },
                    "summary": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
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


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    tenant_id: str
    record_id: str
    title: str
    summary: str


class KnowledgeMcpAdapter:
    """Read-only deterministic MCP adapter; durable business state is out of scope."""

    def __init__(self, records: tuple[KnowledgeRecord, ...]) -> None:
        self._records = records
        self.invocation_count = 0

    async def invoke(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        del idempotency_key
        self.invocation_count += 1
        query = str(arguments["query"]).casefold()
        limit = int(arguments["limit"])
        matches = [
            {
                "record_id": record.record_id,
                "title": record.title,
                "summary": record.summary,
            }
            for record in self._records
            if record.tenant_id == capability.tenant_id
            and (
                query in record.title.casefold()
                or query in record.summary.casefold()
            )
        ][:limit]
        return ToolInvocationResult(
            data={"records": matches, "returned_count": len(matches)}
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
