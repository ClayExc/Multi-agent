"""FP-CTX-001: 每次模型调用使用 ContextEnvelope（Context Manifest）。

Every model call — including every retry attempt and every conversation
round — must carry a freshly built ContextEnvelope whose manifest records
the input estimate up front and whose real input/output token usage is
charged to the cross-turn ledger after the call.  No call path may reach
the runtime with a bare payload.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from flowpilot_agent_runtime import (
    AgentProfile,
    AgentRunRequest,
    FakeAgentRuntime,
    FakeOutcome,
    FakeScenario,
    ProviderSelection,
    RuntimeBudget,
)
from flowpilot_context import (
    ContextBuilder,
    ContextEnvelope,
    ContextPolicy,
    LayerName,
)
from flowpilot_domain import TaskCommand
from flowpilot_graph import (
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)


async def _one_round(
    kernel: RuntimeGraphKernel,
    leases: InMemoryLeaseStore,
    command: TaskCommand,
    *,
    round_index: int,
) -> AgentRunRequest:
    lease = await leases.acquire(
        command.tenant_id,
        command.task_id,
        run_id="run_12345678",
    )
    prepared = await kernel.prepare(
        command,
        execution_ref=f"exec_ref_{round_index}",
        lease=lease,
    )
    assert prepared.request is not None
    result = await kernel.invoke(prepared.request)
    assert result.status.value == "completed"
    # Round ends at the user-input interrupt so the next round can resume.
    await kernel.interrupt_for_user_input(
        prepared.state,
        request_id=f"user_input_{round_index}",
        lease=lease,
    )
    return prepared.request


def _kernel(
    *,
    fake_runtime: FakeAgentRuntime,
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
    maximum_attempts: int = 2,
) -> tuple[RuntimeGraphKernel, InMemoryLeaseStore, InMemoryCheckpointStore]:
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    kernel = RuntimeGraphKernel(
        config=RuntimeGraphConfig(
            graph_version="graph-v1",
            context_policy=context_policy,
            agent=agent_profile,
            provider=provider_selection,
            budget=runtime_budget,
            maximum_attempts=maximum_attempts,
        ),
        context_builder=ContextBuilder(clock=fixed_clock),
        runtime=fake_runtime,
        checkpoints=checkpoints,
        clock=fixed_clock,
    )
    return kernel, leases, checkpoints


def test_every_model_call_carries_a_context_envelope(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    fake_runtime = FakeAgentRuntime(clock=fixed_clock)
    kernel, leases, _ = _kernel(
        fake_runtime=fake_runtime,
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )

    calls: list[AgentRunRequest] = []
    for round_index in range(3):
        command = command_factory(command_id=f"cmd_{round_index:08d}")
        request = asyncio.run(
            _one_round(kernel, leases, command, round_index=round_index)
        )
        calls.append(request)

    # Every runtime call saw an envelope, not a bare payload.
    assert len(fake_runtime.calls) == 3
    for request in calls:
        assert isinstance(request.context, ContextEnvelope)
        assert request.context.context_id.startswith("ctx_")
        assert request.context.manifest.included_refs
        assert "credential" in request.context.manifest.excluded_fields
        assert request.context.manifest.input_tokens_estimated > 0
        assert (
            request.context.manifest.input_tokens_estimated
            <= request.context.policy.token_budget
        )


def test_context_is_rebuilt_before_every_call_and_round_is_visible(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    fake_runtime = FakeAgentRuntime(clock=fixed_clock)
    kernel, leases, _ = _kernel(
        fake_runtime=fake_runtime,
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )

    seen_rounds: list[int] = []
    for round_index in range(3):
        command = command_factory(command_id=f"cmd_{round_index:08d}")
        request = asyncio.run(
            _one_round(kernel, leases, command, round_index=round_index)
        )
        task_state = request.context.layer(LayerName.TASK_STATE).content
        seen_rounds.append(task_state["conversation_round"])

    assert seen_rounds == [0, 1, 2]
    assert kernel.ledger.round_count == 3
    # The fake runtime reports 32 input tokens per call; the ledger charges
    # the real usage, while the manifest carries the pre-call estimate.
    assert kernel.ledger.used_input_tokens == 3 * 32
    assert kernel.ledger.used_output_tokens == 3 * 8


def test_retry_attempt_is_a_model_call_with_its_own_envelope_and_charge(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    """A provider failure retry is a fresh model call with a fresh
    envelope and its own ledger charge (same round, next attempt)."""
    fake_runtime = FakeAgentRuntime(clock=fixed_clock)
    kernel, leases, _ = _kernel(
        fake_runtime=fake_runtime,
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )
    command = command_factory()
    lease = asyncio.run(
        leases.acquire(command.tenant_id, command.task_id, run_id="run_12345678")
    )
    prepared = asyncio.run(
        kernel.prepare(command, execution_ref="exec_ref_1", lease=lease)
    )
    assert prepared.request is not None
    fake_runtime.script(
        prepared.request.request_id,
        [
            FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),
            FakeScenario(outcome=FakeOutcome.COMPLETED),
        ],
    )

    first = asyncio.run(kernel.invoke(prepared.request))
    assert first.status.value == "failed_retryable"
    assert kernel.ledger.round_count == 1
    # Persist the attempt (and its charge) before resuming, as the
    # production flow does.
    retry_outcome = asyncio.run(
        kernel.finalize(prepared.state, first, lease=lease)
    )
    assert retry_outcome.should_retry is True

    # Retry: a fresh model call (one call already charged), new attempt —
    # prepare rebuilds the envelope.
    resumed = asyncio.run(
        kernel.prepare(command, execution_ref="exec_ref_1", lease=lease)
    )
    assert resumed.request is not None
    assert resumed.request.context.manifest.input_tokens_estimated > 0
    assert resumed.state.attempt_count == 2
    assert (
        resumed.request.context.layer(LayerName.TASK_STATE).content[
            "conversation_round"
        ]
        == 1
    )
    second = asyncio.run(kernel.invoke(resumed.request))
    assert second.status.value == "completed"
    assert kernel.ledger.round_count == 2
    assert len(fake_runtime.calls) == 2
    for call in fake_runtime.calls:
        assert isinstance(call.context, ContextEnvelope)
