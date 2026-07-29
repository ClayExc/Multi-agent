from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .models import (
    AgentRunRequest,
    AgentRunResult,
    HandoffProposal,
    RunStatus,
    RuntimeErrorCode,
    RuntimeFailure,
    RuntimeUsage,
    ToolProposal,
)
from .validation import (
    RequestConsistencyError,
    ToolScopeError,
    usage_exceeds_budget,
    validate_request,
    validate_tool_proposals,
)


class FakeOutcome(StrEnum):
    COMPLETED = "completed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_OUTPUT = "invalid_output"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    INTERNAL_FAILURE = "internal_failure"


@dataclass(frozen=True, slots=True)
class FakeScenario:
    outcome: FakeOutcome = FakeOutcome.COMPLETED
    structured_output: Mapping[str, Any] = field(
        default_factory=lambda: {"outcome": "completed"}
    )
    public_summary: str | None = "Deterministic fake runtime completed."
    tool_proposals: tuple[ToolProposal, ...] = ()
    handoff_proposal: HandoffProposal | None = None
    usage: RuntimeUsage = field(
        default_factory=lambda: RuntimeUsage(
            input_tokens=32,
            output_tokens=8,
            total_tokens=40,
            turns=1,
            elapsed_ms=1,
        )
    )
    session_ref: str | None = None
    provider_run_ref: str | None = "provider-run://fake"


class FakeAgentRuntime:
    """Network-free runtime with deterministic, request-scoped scripts."""

    def __init__(
        self,
        *,
        default: FakeScenario | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._default = default or FakeScenario()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._scripts: dict[str, deque[FakeScenario]] = defaultdict(deque)
        self.calls: list[AgentRunRequest] = []

    def script(
        self,
        request_id: str,
        scenarios: Sequence[FakeScenario],
    ) -> None:
        self._scripts[request_id] = deque(scenarios)

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.calls.append(request)
        call_number = len(self.calls)
        now = self._clock().astimezone(UTC)
        try:
            validate_request(request, now=now)
        except RequestConsistencyError:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.REQUEST_INCONSISTENT,
                retryable=False,
                now=now,
            )
        scenarios = self._scripts[request.request_id]
        scenario = scenarios.popleft() if scenarios else self._default
        if scenario.outcome is FakeOutcome.PROVIDER_UNAVAILABLE:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_RETRYABLE,
                code=RuntimeErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                now=now,
                usage=scenario.usage,
            )
        if scenario.outcome is FakeOutcome.GUARDRAIL_BLOCKED:
            return self._failure(
                request,
                call_number,
                status=RunStatus.GUARDRAIL_BLOCKED,
                code=RuntimeErrorCode.GUARDRAIL_BLOCKED,
                retryable=False,
                now=now,
                usage=scenario.usage,
            )
        if scenario.outcome is FakeOutcome.INVALID_OUTPUT:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.INVALID_OUTPUT,
                retryable=False,
                now=now,
                usage=scenario.usage,
            )
        if scenario.outcome is FakeOutcome.INTERNAL_FAILURE:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.INTERNAL,
                retryable=False,
                now=now,
                usage=scenario.usage,
            )
        if usage_exceeds_budget(request, scenario.usage):
            return self._failure(
                request,
                call_number,
                status=RunStatus.BUDGET_EXHAUSTED,
                code=RuntimeErrorCode.BUDGET_EXHAUSTED,
                retryable=False,
                now=now,
                usage=scenario.usage,
            )
        try:
            validate_tool_proposals(request, scenario.tool_proposals)
        except ToolScopeError:
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.TOOL_SCOPE_VIOLATION,
                retryable=False,
                now=now,
                usage=scenario.usage,
            )
        if (
            scenario.handoff_proposal is not None
            and request.agent.maximum_handoffs == 0
        ):
            return self._failure(
                request,
                call_number,
                status=RunStatus.FAILED_FINAL,
                code=RuntimeErrorCode.INVALID_OUTPUT,
                retryable=False,
                now=now,
                usage=scenario.usage,
            )
        return AgentRunResult(
            result_id=self._result_id(request.request_id, call_number),
            request_id=request.request_id,
            status=RunStatus.COMPLETED,
            trace_id=request.trace_id,
            provider_name=request.provider_selection.provider,
            provider_model=request.provider_selection.model,
            structured_output=dict(scenario.structured_output),
            public_reasoning_summary=scenario.public_summary,
            tool_proposals=scenario.tool_proposals,
            handoff_proposal=scenario.handoff_proposal,
            session_ref=scenario.session_ref,
            provider_run_ref=scenario.provider_run_ref,
            usage=scenario.usage,
            completed_at=now,
        )

    def _failure(
        self,
        request: AgentRunRequest,
        call_number: int,
        *,
        status: RunStatus,
        code: RuntimeErrorCode,
        retryable: bool,
        now: datetime,
        usage: RuntimeUsage | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            result_id=self._result_id(request.request_id, call_number),
            request_id=request.request_id,
            status=status,
            trace_id=request.trace_id,
            provider_name=request.provider_selection.provider,
            provider_model=request.provider_selection.model,
            structured_output=None,
            public_reasoning_summary=None,
            usage=usage or RuntimeUsage(),
            error=RuntimeFailure(code=code, retryable=retryable),
            completed_at=now,
        )

    @staticmethod
    def _result_id(request_id: str, call_number: int) -> str:
        suffix = hashlib.sha256(
            f"{request_id}:{call_number}".encode()
        ).hexdigest()[:16]
        return f"arr_{suffix}"
