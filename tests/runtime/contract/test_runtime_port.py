from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from flowpilot_agent_runtime import (
    AgentRunRequest,
    FakeAgentRuntime,
    FakeOutcome,
    FakeScenario,
    RunStatus,
    RuntimeErrorCode,
    RuntimeUsage,
    ToolOperation,
    ToolProposal,
)


def test_fake_runtime_returns_deterministic_structured_result(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    runtime = FakeAgentRuntime(clock=fixed_clock)
    request = request_factory()

    first = asyncio.run(runtime.run(request))
    second_runtime = FakeAgentRuntime(clock=fixed_clock)
    second = asyncio.run(second_runtime.run(request))

    assert first.status is RunStatus.COMPLETED
    assert first.structured_output == {"outcome": "completed"}
    assert first.result_id == second.result_id
    assert first.error is None


def test_request_binding_mismatch_fails_before_scenario_execution(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    runtime = FakeAgentRuntime(
        default=FakeScenario(
            structured_output={"should_not_be_used": True},
        ),
        clock=fixed_clock,
    )

    result = asyncio.run(
        runtime.run(request_factory(request_tenant_id="tenant-b"))
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.structured_output is None
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
    assert result.error.retryable is False


def test_provider_failure_maps_to_only_retryable_runtime_error(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    runtime = FakeAgentRuntime(
        default=FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),
        clock=fixed_clock,
    )

    result = asyncio.run(runtime.run(request_factory()))

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.retryable is True
    assert result.error.detail_ref is None


def test_usage_over_any_hard_limit_stops_the_run(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    runtime = FakeAgentRuntime(
        default=FakeScenario(
            usage=RuntimeUsage(
                input_tokens=32,
                output_tokens=8,
                total_tokens=40,
                tool_calls=3,
                turns=1,
                elapsed_ms=1,
            )
        ),
        clock=fixed_clock,
    )

    result = asyncio.run(runtime.run(request_factory()))

    assert result.status is RunStatus.BUDGET_EXHAUSTED
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.BUDGET_EXHAUSTED
    assert result.error.retryable is False


def test_tool_proposal_cannot_escape_agent_allowlist(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    proposal = ToolProposal(
        proposal_id="tprop_12345678",
        tool="itsm.ticket.create.v1",
        operation=ToolOperation.PROPOSE_WRITE,
        arguments={"summary": "VPN"},
        resource={"type": "ticket"},
        purpose="resolve_vpn_incident",
    )
    runtime = FakeAgentRuntime(
        default=FakeScenario(tool_proposals=(proposal,)),
        clock=fixed_clock,
    )

    result = asyncio.run(runtime.run(request_factory()))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.TOOL_SCOPE_VIOLATION
    assert result.tool_proposals == ()


def test_provider_session_is_diagnostic_result_only(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    runtime = FakeAgentRuntime(
        default=FakeScenario(session_ref="provider-session://opaque"),
        clock=fixed_clock,
    )

    result = asyncio.run(runtime.run(request_factory()))

    assert result.session_ref == "provider-session://opaque"
    assert result.status is RunStatus.COMPLETED
