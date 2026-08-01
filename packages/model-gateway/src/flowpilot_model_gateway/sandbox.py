"""Deterministic, network-free provider for the model gateway.

``SandboxProvider`` is the reference implementation of ``ProviderPort``:
it speaks the wire protocol locally, meters tokens exactly, maps scripted
failures onto ``ProviderWireError`` and never touches credentials or the
network.  It exists so every deterministic acceptance path stays green with
zero provider connectivity (offline all-green).
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .wire import (
    SANDBOX_PROVIDER,
    ProviderToolProposal,
    ProviderWireError,
    ProviderWireErrorCode,
    ProviderWireRequest,
    ProviderWireResponse,
    WireToolOperation,
    meter_input_tokens,
    meter_output_tokens,
    stable_wire_id,
)


@dataclass(frozen=True, slots=True)
class SandboxScenario:
    """Deterministic scripted behavior for a wire request."""

    failure: ProviderWireError | None = None
    output: Mapping[str, Any] | None = None
    tool_proposals: tuple[ProviderToolProposal, ...] = ()


class SandboxProvider:
    """Reference ProviderPort implementation: deterministic, offline, safe."""

    def __init__(
        self,
        *,
        name: str = SANDBOX_PROVIDER,
        model: str = "sandbox-fake",
        default: SandboxScenario | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._default = default or SandboxScenario()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._scripts: dict[str, deque[SandboxScenario]] = defaultdict(deque)
        self.calls: list[ProviderWireRequest] = []

    def script(
        self,
        request_id: str,
        scenarios: Sequence[SandboxScenario] | None = None,
        *,
        failure: ProviderWireError | None = None,
        output: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue deterministic scenarios for a request id (FIFO)."""
        if scenarios is None:
            scenarios = (SandboxScenario(failure=failure, output=output),)
        self._scripts[request_id] = deque(scenarios)

    async def complete(self, request: ProviderWireRequest) -> ProviderWireResponse:
        self.calls.append(request)
        queued = self._scripts.get(request.request_id)
        scenario = queued.popleft() if queued else self._default
        if scenario.failure is not None:
            raise scenario.failure
        output = dict(scenario.output or {"outcome": request.task})
        input_tokens = meter_input_tokens(request.payload)
        output_tokens = meter_output_tokens(output)
        if (
            input_tokens > request.maximum_input_tokens
            or output_tokens > request.maximum_output_tokens
        ):
            raise ProviderWireError(
                ProviderWireErrorCode.BUDGET_EXHAUSTED,
                "sandbox provider exceeded a hard token budget",
            )
        response_id = stable_wire_id(
            "pwr", f"{request.request_id}:{repr(output)}"
        )
        return ProviderWireResponse(
            response_id=response_id,
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_proposals=scenario.tool_proposals,
        )


def sandbox_proposal(
    *,
    proposal_id: str,
    name: str,
    operation: WireToolOperation,
    arguments: Mapping[str, Any],
    purpose: str,
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=proposal_id,
        name=name,
        operation=operation,
        arguments=dict(arguments),
        resource={"type": "tool"},
        purpose=purpose,
    )
