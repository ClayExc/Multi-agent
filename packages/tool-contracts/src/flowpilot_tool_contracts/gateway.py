from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from flowpilot_domain import ToolOperation

from .models import ToolRequest, ToolResult

WORKER_GATEWAY_PORT_VERSION = "flowpilot.worker-gateway.p1.v1"

_THREAD = re.compile(r"^thread_[A-Za-z0-9_-]{8,128}$")
_RUN = re.compile(r"^run_[A-Za-z0-9_-]{8,128}$")


class GatewayPortErrorCode(StrEnum):
    REQUEST_NOT_STUBBED = "PLATFORM_GATEWAY_REQUEST_NOT_STUBBED"
    RESULT_BINDING_MISMATCH = "PLATFORM_GATEWAY_RESULT_BINDING_MISMATCH"
    SCHEMA_PIN_MISMATCH = "PLATFORM_GATEWAY_SCHEMA_PIN_MISMATCH"
    IDEMPOTENCY_CONFLICT = "PLATFORM_GATEWAY_IDEMPOTENCY_CONFLICT"
    WRITE_NOT_SUPPORTED = "PLATFORM_GATEWAY_FAKE_WRITE_NOT_SUPPORTED"


class GatewayPortError(RuntimeError):
    def __init__(self, code: GatewayPortErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class GatewayCall:
    """Worker-visible call metadata; authenticated workload is transport-owned."""

    request: ToolRequest
    thread_id: str
    run_id: str | None
    correlation_id: str

    def __post_init__(self) -> None:
        if _THREAD.fullmatch(self.thread_id) is None:
            raise ValueError("thread_id must be a public v1 identifier")
        if self.run_id is not None and _RUN.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a public v1 identifier")
        if not self.correlation_id or len(self.correlation_id) > 128:
            raise ValueError("correlation_id must contain 1..128 characters")


class GatewayClientPort(Protocol):
    """The only Worker boundary for business-tool execution."""

    async def execute(self, call: GatewayCall) -> ToolResult: ...


class DeterministicGatewayClientFake:
    """Schema-pinned, idempotent read fake for Runtime and Graph tests."""

    def __init__(
        self,
        *,
        schema_pins: Mapping[str, str],
        results_by_request_id: Mapping[str, ToolResult],
    ) -> None:
        if not schema_pins:
            raise ValueError("Gateway fake requires at least one schema pin")
        self._schema_pins = dict(schema_pins)
        self._results = dict(results_by_request_id)
        self._intent_by_key: dict[tuple[str, str, str], str] = {}
        self._result_by_key: dict[tuple[str, str, str], ToolResult] = {}
        self.calls: list[GatewayCall] = []
        self.logical_execution_count = 0

    async def execute(self, call: GatewayCall) -> ToolResult:
        request = call.request
        action = request.planned_action
        if action.tool.operation is not ToolOperation.READ:
            raise GatewayPortError(
                GatewayPortErrorCode.WRITE_NOT_SUPPORTED,
                "deterministic P1 Gateway fake is read-only",
            )
        expected_pin = self._schema_pins.get(action.tool.name)
        if expected_pin != action.tool.schema_hash:
            raise GatewayPortError(
                GatewayPortErrorCode.SCHEMA_PIN_MISMATCH,
                "tool schema does not match the Gateway client pin",
            )
        key = (
            action.tenant_id,
            action.tool.name,
            request.idempotency_key,
        )
        existing_digest = self._intent_by_key.get(key)
        if existing_digest is not None:
            if existing_digest != request.action_digest:
                raise GatewayPortError(
                    GatewayPortErrorCode.IDEMPOTENCY_CONFLICT,
                    "idempotency key is bound to a different action",
                )
            self.calls.append(call)
            return self._result_by_key[key]

        result = self._results.get(request.request_id)
        if result is None:
            raise GatewayPortError(
                GatewayPortErrorCode.REQUEST_NOT_STUBBED,
                "Gateway request does not have a deterministic response",
            )
        if (
            result.request_id != request.request_id
            or result.operation is not action.tool.operation
            or result.policy_decision_id != request.policy_decision_id
        ):
            raise GatewayPortError(
                GatewayPortErrorCode.RESULT_BINDING_MISMATCH,
                "Gateway result does not match its request",
            )
        self.calls.append(call)
        self.logical_execution_count += 1
        self._intent_by_key[key] = request.action_digest
        self._result_by_key[key] = result
        return result
