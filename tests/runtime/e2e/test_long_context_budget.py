"""FP-CTX-004: 长对话硬 Token 预算（逐层 Token 报告）。

A long conversation (up to 50 rounds) runs under a hard cumulative token
budget: every model call is charged with real input/output usage and a
per-layer estimate, the ledger keeps the whole conversation under the
ceiling, and exhaustion terminates the provider loop with an escalation
event (FP-FLOW-006 linkage).  Interrupted runs rebuild both the budget
counters and the layered summary from the Checkpoint instead of
re-charging (FP-FLOW-005 / FP-DATA-001 linkage).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

import pytest
from flowpilot_agent_runtime import (
    AgentProfile,
    FakeAgentRuntime,
    ProviderSelection,
    RuntimeBudget,
)
from flowpilot_context import (
    ContextBuilder,
    ContextEnvelope,
    ContextPolicy,
    LayeredSummary,
    LayerName,
    SummaryItem,
    SummaryKind,
)
from flowpilot_domain import TaskCommand
from flowpilot_graph import (
    GraphError,
    GraphErrorCode,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)

ROUNDS = 50
FAKE_INPUT = 32
FAKE_OUTPUT = 8


def _kernel(
    *,
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
    cumulative_token_budget: int | None = None,
    maximum_conversation_rounds: int = ROUNDS,
    on_escalation: Callable[[object], None] | None = None,
    checkpoints: InMemoryCheckpointStore | None = None,
    runtime: FakeAgentRuntime | None = None,
) -> tuple[
    RuntimeGraphKernel,
    InMemoryLeaseStore,
    InMemoryCheckpointStore,
    FakeAgentRuntime,
]:
    leases = InMemoryLeaseStore(clock=fixed_clock)
    effective_checkpoints = checkpoints or InMemoryCheckpointStore(
        leases=leases
    )
    effective_runtime = runtime or FakeAgentRuntime(clock=fixed_clock)
    kernel = RuntimeGraphKernel(
        config=RuntimeGraphConfig(
            graph_version="graph-v1",
            context_policy=context_policy,
            agent=agent_profile,
            provider=provider_selection,
            budget=runtime_budget,
            cumulative_token_budget=cumulative_token_budget,
            maximum_conversation_rounds=maximum_conversation_rounds,
            on_escalation=on_escalation,
        ),
        context_builder=ContextBuilder(clock=fixed_clock),
        runtime=effective_runtime,
        checkpoints=effective_checkpoints,
        clock=fixed_clock,
    )
    return kernel, leases, effective_checkpoints, effective_runtime


async def _one_round(
    kernel: RuntimeGraphKernel,
    leases: InMemoryLeaseStore,
    command: TaskCommand,
    *,
    round_index: int,
    interrupt: bool = True,
) -> ContextEnvelope:
    lease = await leases.acquire(
        command.tenant_id, command.task_id, run_id="run_12345678"
    )
    prepared = await kernel.prepare(
        command,
        execution_ref=f"exec_ref_{round_index}",
        lease=lease,
    )
    assert prepared.request is not None
    result = await kernel.invoke(prepared.request)
    assert result.status.value == "completed"
    if interrupt:
        await kernel.interrupt_for_user_input(
            prepared.state,
            request_id=f"user_input_{round_index}",
            lease=lease,
        )
    return prepared.request.context


def test_fifty_round_conversation_stays_under_hard_budget(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    hard_budget = ROUNDS * (FAKE_INPUT + FAKE_OUTPUT) + 100  # 2100
    kernel, leases, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
        cumulative_token_budget=hard_budget,
        maximum_conversation_rounds=ROUNDS,
    )

    envelopes: list[ContextEnvelope] = []
    for round_index in range(ROUNDS):
        command = command_factory(command_id=f"cmd_{round_index:08d}")
        envelope = asyncio.run(
            _one_round(
                kernel, leases, command, round_index=round_index
            )
        )
        envelopes.append(envelope)

    # The whole conversation stayed under the hard ceiling.  Round 50 is
    # the last allowed round: the token budget was never crossed, and the
    # conversation is naturally exhausted on the round dimension.
    assert kernel.ledger.round_count == ROUNDS
    assert kernel.ledger.used_input_tokens == ROUNDS * FAKE_INPUT
    assert kernel.ledger.used_output_tokens == ROUNDS * FAKE_OUTPUT
    assert kernel.ledger.used_total_tokens == ROUNDS * (FAKE_INPUT + FAKE_OUTPUT)
    assert kernel.ledger.used_total_tokens < hard_budget
    assert kernel.ledger.remaining_tokens == (
        hard_budget - kernel.ledger.used_total_tokens
    )
    assert kernel.ledger.exhaustion.reason_code == "maximum_rounds"
    assert kernel.ledger.exhaustion.used_total_tokens < hard_budget
    assert kernel.escalation_events == []

    # Every call carried a manifest with input/output accounting and the
    # per-layer distribution is real (sum of layer estimates > 0).
    for envelope in envelopes:
        assert envelope.manifest.input_tokens_estimated > 0
    report = kernel.ledger.report()
    assert report["round_count"] == ROUNDS
    assert len(report["turns"]) == ROUNDS
    assert report["used_total_tokens"] == kernel.ledger.used_total_tokens
    assert report["layer_totals"], "per-layer token report must be non-empty"
    assert sum(report["layer_totals"].values()) > 0
    assert all(
        turn["input_tokens"] == FAKE_INPUT and turn["output_tokens"] == FAKE_OUTPUT
        for turn in report["turns"]
    )


def test_budget_exhaustion_terminates_and_escalates(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    received: list[object] = []
    # 3 rounds exactly fill the budget (3 * 40 = 120 = budget); the 4th
    # round is then refused up front, before any provider call.
    kernel, leases, _, fake_runtime = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
        cumulative_token_budget=120,
        maximum_conversation_rounds=ROUNDS,
        on_escalation=received.append,
    )

    for round_index in range(3):
        command = command_factory(command_id=f"cmd_{round_index:08d}")
        asyncio.run(
            _one_round(kernel, leases, command, round_index=round_index)
        )
    assert kernel.ledger.round_count == 3
    assert kernel.ledger.used_total_tokens == 120
    assert kernel.ledger.is_exhausted is True
    assert kernel.ledger.exhaustion.reason_code == "cumulative_tokens"

    # The next model call is refused at prepare time: BUDGET_EXHAUSTED
    # terminates the provider loop and escalates, with zero provider calls.
    calls_before = len(fake_runtime.calls)
    command = command_factory(command_id="cmd_00000003")
    lease = asyncio.run(
        leases.acquire(
            command.tenant_id, command.task_id, run_id="run_12345678"
        )
    )
    with pytest.raises(GraphError) as captured:
        asyncio.run(
            kernel.prepare(command, execution_ref="exec_ref_3", lease=lease)
        )
    assert captured.value.code is GraphErrorCode.BUDGET_EXHAUSTED
    assert captured.value.retryable is False
    assert len(fake_runtime.calls) == calls_before

    # The escalation trail carries the exhaustion event to both the list
    # and the sink, with the reason and no ledger mutation.
    assert kernel.ledger.used_total_tokens == 120
    assert received == kernel.escalation_events
    exhaustion_event = kernel.escalation_events[-1]
    assert exhaustion_event["event_type"] == "context_budget_exhausted"
    assert exhaustion_event["boundary"] == "budget"
    assert exhaustion_event["reason_code"] == "cumulative_tokens"
    assert exhaustion_event["event_id"].startswith("evt_")


def test_round_ceiling_terminates_after_maximum_rounds(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    kernel, leases, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
        cumulative_token_budget=1_000_000,
        maximum_conversation_rounds=3,
    )

    for round_index in range(3):
        command = command_factory(command_id=f"cmd_{round_index:08d}")
        asyncio.run(
            _one_round(kernel, leases, command, round_index=round_index)
        )
    assert kernel.ledger.round_count == 3

    # Round 4 is refused before any provider call (round ceiling reached).
    with pytest.raises(GraphError) as captured:
        asyncio.run(
            kernel.prepare(
                command_factory(command_id="cmd_00000003"),
                execution_ref="exec_ref_3",
                lease=asyncio.run(
                    leases.acquire(
                        "tenant-a", "task_12345678", run_id="run_12345678"
                    )
                ),
            )
        )
    assert captured.value.code is GraphErrorCode.BUDGET_EXHAUSTED
    assert kernel.escalation_events[-1]["reason_code"] == "maximum_rounds"


def test_restart_rebuilds_budget_and_summary_from_checkpoint(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    """Interrupted run: a fresh kernel over the same Checkpoint store
    rebuilds the ledger counters and the layered summary — no double
    charging, and the summary rides into the next envelope as L3."""
    kernel1, leases, checkpoints, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
        cumulative_token_budget=100_000,
    )
    summary = LayeredSummary(
        items=(
            SummaryItem(
                kind=SummaryKind.VERIFIED,
                text="policy allows VPN for production",
                source_refs=("tool://policy/v1",),
            ),
            SummaryItem(
                kind=SummaryKind.CLAIMED,
                text="user claims VPN is flaky",
                source_refs=("message://t/1",),
            ),
        )
    )

    # Round 0: run and park at the user interrupt with a summary.
    command0 = command_factory(command_id="cmd_00000000")
    lease = asyncio.run(
        leases.acquire(
            command0.tenant_id, command0.task_id, run_id="run_12345678"
        )
    )
    prepared0 = asyncio.run(
        kernel1.prepare(command0, execution_ref="exec_ref_0", lease=lease)
    )
    assert prepared0.request is not None
    result0 = asyncio.run(kernel1.invoke(prepared0.request))
    assert result0.status.value == "completed"
    summarized = kernel1.append_summary(prepared0.state, summary=summary)
    asyncio.run(
        kernel1.interrupt_for_user_input(
            summarized,
            request_id="user_input_0",
            lease=lease,
        )
    )
    # Round 1: run and interrupt again (checkpoint now has round=2).
    command1 = command_factory(command_id="cmd_00000001")
    asyncio.run(
        _one_round(kernel1, leases, command1, round_index=1)
    )
    assert kernel1.ledger.round_count == 2

    # Restart: a brand-new kernel over the same Checkpoint store.
    kernel2, _, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
        cumulative_token_budget=100_000,
        checkpoints=checkpoints,
    )
    assert kernel2.ledger.round_count == 0

    command2 = command_factory(command_id="cmd_00000002")
    prepared2 = asyncio.run(
        kernel2.prepare(command2, execution_ref="exec_ref_2", lease=lease)
    )
    assert prepared2.request is not None
    # Budget counters were rebuilt from the Checkpoint: this call is round
    # 2, not round 0, so usage is not double-counted.
    assert kernel2.ledger.round_count == 2
    result2 = asyncio.run(kernel2.invoke(prepared2.request))
    assert result2.status.value == "completed"
    assert kernel2.ledger.round_count == 3
    assert kernel2.ledger.used_input_tokens == 3 * FAKE_INPUT
    assert kernel2.ledger.used_output_tokens == 3 * FAKE_OUTPUT

    # The layered summary survived the restart and rides as the L3 layer.
    assert prepared2.request.context.layer(
        LayerName.CONVERSATION_SUMMARY
    ).content["items"][0]["kind"] == SummaryKind.VERIFIED.value
    sections = kernel2.append_summary(
        prepared2.state, summary=summary
    ).summary.sections()
    assert len(sections[SummaryKind.VERIFIED]) == 1
    assert len(sections[SummaryKind.CLAIMED]) == 1
