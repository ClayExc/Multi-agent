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

TOOL_NAME = "ticket.update.v1"
TICKET_MCP_VERSION = "flowpilot.ticket-mcp.p1.v1"
TICKET_UPDATE_SCOPE = "ticket.update"
LEGACY_TICKET_SCHEMA_PIN = (
    "sha256:fa39a6eb55d2d2bf68174a47dcb00d63a58e771e7ba5e3781cde4d716a319c04"
)

_TICKET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_TEXT_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,2048}$")

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ticket_id", "status"],
    "properties": {
        "ticket_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "status": {
            "type": "string",
            "enum": ["in_progress", "resolved"],
        },
        "summary": {"type": "string", "minLength": 1, "maxLength": 2048},
    },
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ticket_id", "status"],
    "properties": {
        "ticket_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "status": {
            "type": "string",
            "enum": ["in_progress", "resolved"],
        },
        "summary": {"type": "string", "minLength": 1, "maxLength": 2048},
    },
}

TICKET_CONTRACT = ToolContract.create(
    name=TOOL_NAME,
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
)
TICKET_SCHEMA_PIN = (
    "sha256:1e68e4ae27bd8024d9b0e8864b5bc6a816848b9023ef5ed004b33c4880f1429d"
)


if TICKET_CONTRACT.schema_hash != TICKET_SCHEMA_PIN:
    raise RuntimeError("ticket.update.v1 schema drifted from its fixed pin")


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TicketRecord:
    """Authoritative in-memory ticket state exposed by the mock Ticket MCP."""

    tenant_id: str
    ticket_id: str
    status: str
    summary: str | None

    def __post_init__(self) -> None:
        if not self.tenant_id or len(self.tenant_id) > 128:
            raise ValueError("tenant_id must be a bounded non-empty string")
        if _TICKET_ID_PATTERN.fullmatch(self.ticket_id) is None:
            raise ValueError("ticket_id has an invalid format")
        if self.status not in {"in_progress", "resolved"}:
            raise ValueError("ticket status is unsupported")
        if self.summary is not None and _SAFE_TEXT_PATTERN.fullmatch(
            self.summary
        ) is None:
            raise ValueError("ticket summary contains unsafe characters")

    def to_mapping(self) -> dict[str, str]:
        value: dict[str, str] = {
            "ticket_id": self.ticket_id,
            "status": self.status,
        }
        if self.summary is not None:
            value["summary"] = self.summary
        return value


class TicketMcpAdapter:
    """Deterministic write adapter with server-side idempotency and readback.

    The mock upstream is tenant-bound per instance and keeps exactly one
    ticket per ``(ticket_id, idempotency_key)`` pair; replays return the
    stored authoritative state. Failure modes mirror the write protocols
    exercised by the platform recovery tests: ``verified``, ``not_sent``,
    ``rejected``, ``unknown_executed``, ``unknown_not_executed``,
    ``readback_unavailable``, ``readback_mismatch`` and
    ``reconcile_unavailable``.
    """

    def __init__(
        self,
        tenant_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not tenant_id or len(tenant_id) > 128:
            raise ValueError("tenant_id must be a bounded non-empty string")
        self._tenant_id = tenant_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self.mode = "verified"
        self.invocation_count = 0
        self.reconciliation_count = 0
        self.logical_ticket_count = 0
        self._tickets: dict[tuple[str, str], TicketRecord] = {}
        self.ticket_ids: list[str] = []
        self.failure: Exception | None = None

    async def invoke(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        self.invocation_count += 1
        if self.failure is not None:
            raise self.failure
        self._verify_capability(capability)
        self._validate_arguments(arguments)
        if self.mode == "not_sent":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.NOT_SENT,
                "PROVIDER_NOT_SENT",
                "upstream invocation was not sent",
            )
        if self.mode == "rejected":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "PROVIDER_REJECTED",
                "upstream rejected the request",
            )
        if self.mode == "unknown_not_executed":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.OUTCOME_UNKNOWN,
                "PROVIDER_TIMEOUT",
                "upstream outcome is unknown",
            )
        key = (str(arguments["ticket_id"]), idempotency_key)
        if key not in self._tickets:
            self.logical_ticket_count += 1
            record = TicketRecord(
                tenant_id=self._tenant_id,
                ticket_id=str(arguments["ticket_id"]),
                status=str(arguments["status"]),
                summary=(
                    str(arguments["summary"])
                    if arguments.get("summary") is not None
                    else None
                ),
            )
            self._tickets[key] = record
            self.ticket_ids.append(record.ticket_id)
        if self.mode == "unknown_executed":
            raise GatewayAdapterError(
                GatewayAdapterDisposition.OUTCOME_UNKNOWN,
                "PROVIDER_TIMEOUT",
                "upstream outcome is unknown",
            )
        return ToolInvocationResult(data=self._tickets[key].to_mapping())

    async def readback(
        self,
        *,
        arguments: Mapping[str, Any],
        invocation: ToolInvocationResult,
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReadbackResult:
        del invocation, capability
        self._validate_arguments(arguments)
        if self.mode == "readback_unavailable":
            raise RuntimeError("readback unavailable")
        stored = self._tickets.get(
            (str(arguments["ticket_id"]), idempotency_key)
        )
        data: Mapping[str, Any] = stored.to_mapping() if stored is not None else {}
        matched = (
            stored is not None
            and stored.status == str(arguments["status"])
            and self.mode != "readback_mismatch"
        )
        return ReadbackResult(
            data=data,
            evidence_ref="evidence://ticket/readback",
            observed_ref=f"ticket://observed/{arguments['ticket_id']}",
            matched=matched,
        )

    async def reconcile(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReconciliationResult:
        del capability
        self._validate_arguments(arguments)
        self.reconciliation_count += 1
        if self.mode == "reconcile_unavailable":
            raise RuntimeError("reconciliation unavailable")
        stored = self._tickets.get(
            (str(arguments["ticket_id"]), idempotency_key)
        )
        if stored is None:
            return ReconciliationResult(
                disposition=ReconciliationDisposition.CONFIRMED_NOT_EXECUTED,
                data=None,
                evidence_ref="evidence://idempotency/absent",
                observed_ref="idempotency://absent",
                method="upstream_idempotency_lookup",
            )
        return ReconciliationResult(
            disposition=ReconciliationDisposition.VERIFIED,
            data=stored.to_mapping(),
            evidence_ref="evidence://idempotency/present",
            observed_ref=f"idempotency://{stored.ticket_id}",
            method="upstream_idempotency_lookup",
        )

    def records(self) -> tuple[TicketRecord, ...]:
        """Authoritative ticket states created by this mock upstream."""
        return tuple(
            self._tickets[key] for key in sorted(self._tickets, key=str)
        )

    def _verify_capability(self, capability: CapabilityHandle) -> None:
        now = _utc(self._clock(), "ticket clock")
        if (
            TICKET_UPDATE_SCOPE not in capability.scopes
            or capability.tenant_id != self._tenant_id
            or not capability.subject_id
            or not capability.subject_acl
            or not capability.workload_principal_ref
            or not capability.purpose
            or now < capability.issued_at
            or now >= capability.expires_at
        ):
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "TICKET_ACCESS_DENIED",
                "ticket access capability was denied",
            )

    @staticmethod
    def _validate_arguments(arguments: Mapping[str, Any]) -> None:
        ticket_id = arguments.get("ticket_id")
        status = arguments.get("status")
        if (
            not isinstance(ticket_id, str)
            or _TICKET_ID_PATTERN.fullmatch(ticket_id) is None
        ):
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "TICKET_ARGUMENTS_REJECTED",
                "ticket arguments did not pass deterministic validation",
            )
        if status not in {"in_progress", "resolved"}:
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "TICKET_ARGUMENTS_REJECTED",
                "ticket arguments did not pass deterministic validation",
            )
        summary = arguments.get("summary")
        if summary is not None and (
            not isinstance(summary, str)
            or _SAFE_TEXT_PATTERN.fullmatch(summary) is None
        ):
            raise GatewayAdapterError(
                GatewayAdapterDisposition.REJECTED,
                "TICKET_ARGUMENTS_REJECTED",
                "ticket arguments did not pass deterministic validation",
            )


__all__ = [
    "INPUT_SCHEMA",
    "LEGACY_TICKET_SCHEMA_PIN",
    "OUTPUT_SCHEMA",
    "TICKET_CONTRACT",
    "TICKET_MCP_VERSION",
    "TICKET_SCHEMA_PIN",
    "TICKET_UPDATE_SCOPE",
    "TOOL_NAME",
    "TicketMcpAdapter",
    "TicketRecord",
]
