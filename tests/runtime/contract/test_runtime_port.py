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
    SandboxAdapter,
    ToolOperation,
    ToolProposal,
)
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    DeterministicModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ProviderRoute,
    ProviderWireError,
    ProviderWireErrorCode,
    ProviderWireRequest,
    ProviderWireResponse,
    SandboxProvider,
    SandboxScenario,
    WireToolOperation,
    meter_input_tokens,
    meter_output_tokens,
    run_provider_conformance,
    sandbox_proposal,
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


# ---------------------------------------------------------------------------
# Sandbox adapter conformance (FP-AGT-002: Provider Adapter 遵循统一端口)
# ---------------------------------------------------------------------------


def _sandbox_gateway(
    provider: SandboxProvider | None = None,
    *,
    routes: tuple[ProviderRoute, ...] | None = None,
) -> DeterministicModelGateway:
    effective = provider or SandboxProvider(
        name="test-provider", model="sandbox-fake"
    )
    if routes is None:
        routes = (
            ProviderRoute(
                provider="test-provider",
                model="sandbox-fake",
                maximum_classification=DataClassification.RESTRICTED,
            ),
        )
    return DeterministicModelGateway(
        routes=routes,
        providers={"test-provider": effective},
    )


def _sandbox_adapter(
    gateway: DeterministicModelGateway | None = None,
    *,
    fixed_clock: Callable[[], datetime],
) -> tuple[SandboxAdapter, DeterministicModelGateway]:
    effective_gateway = gateway or _sandbox_gateway()
    adapter = SandboxAdapter(effective_gateway, clock=fixed_clock)
    return adapter, effective_gateway


def test_sandbox_adapter_returns_deterministic_result_with_exact_usage(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    first_adapter, gateway = _sandbox_adapter(fixed_clock=fixed_clock)
    second_adapter, _ = _sandbox_adapter(fixed_clock=fixed_clock)
    request = request_factory()

    first = asyncio.run(first_adapter.run(request))
    second = asyncio.run(second_adapter.run(request))

    assert first.status is RunStatus.COMPLETED
    assert first.structured_output == {"outcome": "summarize"}
    assert first.result_id == second.result_id
    assert first.structured_output == second.structured_output
    # Usage is exact against the wire metering formula, derived from the
    # actual payload the adapter sent to the gateway.
    wire_payload = gateway.calls[0].payload
    assert first.usage.input_tokens == meter_input_tokens(wire_payload)
    assert first.usage.output_tokens == meter_output_tokens(first.structured_output)
    assert first.usage.total_tokens == (
        first.usage.input_tokens + first.usage.output_tokens
    )
    assert first.usage.turns == 1
    assert first.usage.tool_calls == 0
    assert first.provider_name == "test-provider"
    assert first.provider_run_ref.startswith("provider-run://test-provider/mgr_")
    assert first.error is None


def test_sandbox_adapter_maps_provider_unavailable_to_only_retryable_error(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    provider = SandboxProvider(
        name="test-provider",
        default=SandboxScenario(
            failure=ProviderWireError(
                ProviderWireErrorCode.PROVIDER_UNAVAILABLE,
                "sandbox provider is unavailable",
                retryable=True,
            )
        ),
    )
    adapter, gateway = _sandbox_adapter(
        _sandbox_gateway(provider), fixed_clock=fixed_clock
    )

    result = asyncio.run(adapter.run(request_factory()))

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.structured_output is None
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.retryable is True
    assert len(gateway.calls) == 1


def test_sandbox_adapter_rejects_binding_mismatch_before_gateway_call(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    adapter, gateway = _sandbox_adapter(fixed_clock=fixed_clock)

    result = asyncio.run(
        adapter.run(request_factory(request_tenant_id="tenant-b"))
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.REQUEST_INCONSISTENT
    assert result.error.retryable is False
    assert gateway.calls == []


def test_sandbox_adapter_blocks_out_of_scope_tool_proposal(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    # knowledge-agent only allows knowledge.search.v1 READ; the wire response
    # proposes an out-of-scope write tool.
    proposal = sandbox_proposal(
        proposal_id="tprop_00000001",
        name="itsm.ticket.create.v1",
        operation=WireToolOperation.PROPOSE_WRITE,
        arguments={"summary": "VPN"},
        purpose="resolve_vpn_incident",
    )
    provider = SandboxProvider(
        name="test-provider",
        default=SandboxScenario(tool_proposals=(proposal,)),
    )
    adapter, _ = _sandbox_adapter(_sandbox_gateway(provider), fixed_clock=fixed_clock)

    result = asyncio.run(adapter.run(request_factory()))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.structured_output is None
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.TOOL_SCOPE_VIOLATION
    assert result.tool_proposals == ()


def test_sandbox_adapter_passes_in_scope_tool_proposal_through(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    proposal = sandbox_proposal(
        proposal_id="tprop_00000002",
        name="knowledge.search.v1",
        operation=WireToolOperation.READ,
        arguments={"query": "vpn"},
        purpose="resolve_vpn_incident",
    )
    provider = SandboxProvider(
        name="test-provider",
        default=SandboxScenario(tool_proposals=(proposal,)),
    )
    adapter, _ = _sandbox_adapter(_sandbox_gateway(provider), fixed_clock=fixed_clock)

    result = asyncio.run(adapter.run(request_factory()))

    assert result.status is RunStatus.COMPLETED
    assert len(result.tool_proposals) == 1
    assert result.tool_proposals[0].tool == "knowledge.search.v1"
    assert result.tool_proposals[0].operation is ToolOperation.READ


def test_sandbox_adapter_maps_every_gateway_error_to_stable_runtime_code(
    request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable[[], datetime],
) -> None:
    # MODEL_BUDGET_EXHAUSTED via an over-budget wire output.
    oversized = SandboxProvider(
        name="test-provider",
        default=SandboxScenario(output={"text": "x" * 5000}),
    )
    adapter, _ = _sandbox_adapter(
        _sandbox_gateway(oversized), fixed_clock=fixed_clock
    )
    budget_result = asyncio.run(adapter.run(request_factory()))
    assert budget_result.status is RunStatus.BUDGET_EXHAUSTED
    assert budget_result.error is not None
    assert budget_result.error.code is RuntimeErrorCode.BUDGET_EXHAUSTED
    assert budget_result.error.retryable is False

    # MODEL_ROUTE_DENIED via an empty route table.
    adapter, _ = _sandbox_adapter(
        _sandbox_gateway(routes=()), fixed_clock=fixed_clock
    )
    route_result = asyncio.run(adapter.run(request_factory()))
    assert route_result.status is RunStatus.FAILED_FINAL
    assert route_result.error is not None
    assert route_result.error.code is RuntimeErrorCode.INTERNAL
    assert route_result.error.retryable is False
    assert route_result.error.detail_ref == "model_route_denied"

    # MODEL_INVALID_OUTPUT via a wire invalid-output failure.
    invalid = SandboxProvider(
        name="test-provider",
        default=SandboxScenario(
            failure=ProviderWireError(
                ProviderWireErrorCode.INVALID_OUTPUT,
                "sandbox provider returned an invalid output",
            )
        ),
    )
    adapter, _ = _sandbox_adapter(_sandbox_gateway(invalid), fixed_clock=fixed_clock)
    invalid_result = asyncio.run(adapter.run(request_factory()))
    assert invalid_result.status is RunStatus.FAILED_FINAL
    assert invalid_result.error is not None
    assert invalid_result.error.code is RuntimeErrorCode.INVALID_OUTPUT
    assert invalid_result.error.retryable is False


def test_sandbox_provider_conformance_battery_passes(
    fixed_clock: Callable[[], datetime],
) -> None:
    first = SandboxProvider(name="test-provider", clock=fixed_clock)
    second = SandboxProvider(name="test-provider", clock=fixed_clock)

    first_report = asyncio.run(
        run_provider_conformance(first, clock=fixed_clock)
    )
    second_report = asyncio.run(
        run_provider_conformance(second, clock=fixed_clock)
    )

    assert first_report.passed is True
    assert second_report.passed is True
    names = [check.name for check in first_report.checks]
    assert names == [
        "correlation",
        "provider_identity",
        "credential_free",
        "exact_input_metering",
        "exact_output_metering",
        "budget_bounds",
        "determinism",
        "unavailable_mapping",
    ]
    assert first_report.to_mapping()["schema"] == (
        "flowpilot.provider-conformance.v1"
    )


def test_gateway_rejects_port_that_violates_hard_token_budget() -> None:
    class OverBudgetPort:
        async def complete(
            self, request: ProviderWireRequest
        ) -> ProviderWireResponse:
            return ProviderWireResponse(
                response_id="pwr_overbudget",
                request_id=request.request_id,
                provider="test-provider",
                model="sandbox-fake",
                output={"outcome": "summarize"},
                input_tokens=request.maximum_input_tokens + 1,
                output_tokens=1,
            )

    gateway = DeterministicModelGateway(
        routes=(
            ProviderRoute(
                provider="test-provider",
                model="sandbox-fake",
                maximum_classification=DataClassification.RESTRICTED,
            ),
        ),
        providers={"test-provider": OverBudgetPort()},
    )

    try:
        asyncio.run(gateway.complete(_gateway_request()))
    except ModelGatewayError as exc:
        assert exc.code is ModelGatewayErrorCode.BUDGET_EXHAUSTED
        assert exc.retryable is False
    else:
        raise AssertionError("over-budget port must be rejected by the gateway")


def _gateway_request():
    from flowpilot_model_gateway import ModelRequest, ModelTask

    return ModelRequest(
        request_id="arq_12345678",
        task_id="task_12345678",
        tenant_id="tenant-a",
        task=ModelTask.SUMMARIZE,
        payload={"agent_id": "knowledge-agent", "purpose": "it_support"},
        data_classification=DataClassification.CONFIDENTIAL,
        provider_allowlist=("test-provider",),
        maximum_input_tokens=4096,
        maximum_output_tokens=1024,
    )
