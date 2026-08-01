"""Vendor-neutral provider wire protocol (candidate, in-package).

Design notes
------------
- ``ProviderWireRequest`` / ``ProviderWireResponse`` are the canonical
  serializable shapes exchanged with a real provider adapter.  They are the
  *wire* view of a model call: no runtime, graph or tenant objects leak into
  the provider boundary.
- ``ProviderPort`` is the vendor-neutral completion port.  A provider
  adapter implements it; ``DeterministicModelGateway`` routes to registered
  ports by provider name.
- ``ProviderWireError`` is the only failure channel.  The contract keeps
  exactly one retryable code (``PROVIDER_UNAVAILABLE``); everything else is
  final.  The gateway maps wire errors onto the stable gateway error codes
  without inventing new ones.
- This is a *candidate additive* protocol.  The v1 jsonschema
  (``provider-wire.v1.schema.json``) requires an S1 RFC before promotion;
  until then this module is the single source of truth and the conformance
  battery below is the executable contract.
- Sandbox determinism: token metering is a pure function of the wire
  payload/output (see ``meter_input_tokens`` / ``meter_output_tokens``), so
  the same request always produces the same response and the same exact
  usage.  Zero credentials, zero network.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from flowpilot_domain import DataClassification

# Provider names are stable registry keys (vendor-neutral spelling).
SANDBOX_PROVIDER = "sandbox"

# Mirrors the runtime's forbidden-key set (validation.py).  A conformant
# provider must never echo credential-shaped fields back to the runtime.
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer_token",
        "cookie",
        "credential",
        "credentials",
        "private_key",
        "provider_session",
        "session_ref",
    }
)


class WireToolOperation(StrEnum):
    READ = "read"
    PROPOSE_WRITE = "propose_write"


class ProviderWireErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INVALID_OUTPUT = "INVALID_OUTPUT"


class ProviderWireError(RuntimeError):
    """Deterministic provider failure carried across the wire boundary."""

    def __init__(
        self,
        code: ProviderWireErrorCode,
        safe_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProviderWireRequest:
    request_id: str
    task: str
    payload: Mapping[str, Any]
    data_classification: DataClassification
    maximum_input_tokens: int
    maximum_output_tokens: int

    def __post_init__(self) -> None:
        if not self.request_id or not self.task:
            raise ValueError("wire requests require a request id and task")
        if self.maximum_input_tokens < 1 or self.maximum_output_tokens < 1:
            raise ValueError("wire token budgets must be positive")


@dataclass(frozen=True, slots=True)
class ProviderToolProposal:
    proposal_id: str
    name: str
    operation: WireToolOperation
    arguments: Mapping[str, Any]
    resource: Mapping[str, Any]
    purpose: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.name or not self.purpose:
            raise ValueError("wire tool proposals require identity and purpose")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("wire tool proposal evidence references must be unique")


@dataclass(frozen=True, slots=True)
class ProviderWireResponse:
    response_id: str
    request_id: str
    provider: str
    model: str
    output: Mapping[str, Any]
    input_tokens: int
    output_tokens: int
    tool_proposals: tuple[ProviderToolProposal, ...] = ()

    def __post_init__(self) -> None:
        if not self.response_id or not self.provider or not self.model:
            raise ValueError("wire responses require identity and provider metadata")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("wire usage cannot be negative")


class ProviderPort(Protocol):
    async def complete(self, request: ProviderWireRequest) -> ProviderWireResponse: ...


def meter_input_tokens(payload: Mapping[str, Any]) -> int:
    """Deterministic input metering: stable encoding of the sorted payload."""
    encoded = repr(sorted(payload.items())).encode()
    return max(1, len(encoded) // 4)


def meter_output_tokens(output: Mapping[str, Any]) -> int:
    """Deterministic output metering: stable encoding of the output."""
    encoded = repr(output).encode()
    return max(1, len(encoded) // 4)


def stable_wire_id(prefix: str, value: str) -> str:
    suffix = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"{prefix}_{suffix}"


def assert_wire_credential_free(value: object) -> None:
    """Reject credential-shaped keys anywhere in a wire value (deep scan)."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"wire value contains a forbidden credential field: {key}"
                )
            assert_wire_credential_free(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            assert_wire_credential_free(child)


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    name: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderConformanceReport:
    provider_name: str
    checks: tuple[ConformanceCheck, ...]
    passed: bool
    completed_at: datetime

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": "flowpilot.provider-conformance.v1",
            "provider_name": self.provider_name,
            "passed": self.passed,
            "completed_at": self.completed_at.astimezone(UTC).isoformat(),
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "detail": check.detail,
                }
                for check in self.checks
            ],
        }


async def run_provider_conformance(
    provider: ProviderPort,
    *,
    clock: Callable[[], datetime] | None = None,
    request_id: str = "conformance_req_0000000000000000",
) -> ProviderConformanceReport:
    """Run the deterministic conformance battery against a ProviderPort.

    The battery checks properties every conformant provider must satisfy:
    request/response correlation, provider identity, deterministic output
    and exact usage against the documented metering, budget enforcement at
    the wire level, credential-free responses, and the one-retryable-code
    failure mapping (only when the provider exposes the sandbox scripting
    interface).
    """
    checks: list[ConformanceCheck] = []
    now = clock() if clock is not None else datetime.now(UTC)
    provider_name = getattr(provider, "name", "provider")

    def record(name: str, passed: bool, detail: str | None = None) -> None:
        checks.append(ConformanceCheck(name=name, passed=passed, detail=detail))

    request = ProviderWireRequest(
        request_id=request_id,
        task="summarize",
        payload={"agent_id": "knowledge-agent", "purpose": "it_support"},
        data_classification=DataClassification.INTERNAL,
        maximum_input_tokens=4096,
        maximum_output_tokens=1024,
    )
    try:
        first = await provider.complete(request)
        correlation = first.request_id == request.request_id
        record(
            "correlation",
            correlation,
            None if correlation else f"response {first.request_id!r}",
        )
        identity = bool(first.provider) and bool(first.model)
        record("provider_identity", identity)
        record(
            "credential_free",
            _wire_value_is_credential_free(first),
            None,
        )
        expected_input = meter_input_tokens(request.payload)
        expected_output = meter_output_tokens(first.output)
        record(
            "exact_input_metering",
            first.input_tokens == expected_input,
            f"metered={first.input_tokens} expected={expected_input}",
        )
        record(
            "exact_output_metering",
            first.output_tokens == expected_output,
            f"metered={first.output_tokens} expected={expected_output}",
        )
        within_budget = (
            first.input_tokens <= request.maximum_input_tokens
            and first.output_tokens <= request.maximum_output_tokens
        )
        record("budget_bounds", within_budget)

        second = await provider.complete(request)
        deterministic = (
            second.output == first.output
            and second.input_tokens == first.input_tokens
            and second.output_tokens == first.output_tokens
            and second.response_id == first.response_id
        )
        record(
            "determinism",
            deterministic,
            None if deterministic else "repeated response diverged",
        )
    except Exception as exc:  # noqa: BLE001 - battery reports, never raises
        record("completion", False, f"{type(exc).__name__}: {exc}")

    script = getattr(provider, "script", None)
    if callable(script):
        unavailable = ProviderWireError(
            ProviderWireErrorCode.PROVIDER_UNAVAILABLE,
            "sandbox provider is unavailable",
            retryable=True,
        )
        script(request_id, failure=unavailable)
        try:
            await provider.complete(request)
            record("unavailable_raises", False, "expected ProviderWireError")
        except ProviderWireError as exc:
            record(
                "unavailable_mapping",
                exc.code is ProviderWireErrorCode.PROVIDER_UNAVAILABLE
                and exc.retryable is True,
                f"code={exc.code.value} retryable={exc.retryable}",
            )

    passed = all(check.passed for check in checks)
    return ProviderConformanceReport(
        provider_name=provider_name,
        checks=tuple(checks),
        passed=passed,
        completed_at=now,
    )


def _wire_value_is_credential_free(response: ProviderWireResponse) -> bool:
    try:
        assert_wire_credential_free(response.output)
        for proposal in response.tool_proposals:
            assert_wire_credential_free(proposal.arguments)
            assert_wire_credential_free(proposal.resource)
    except ValueError:
        return False
    return True
