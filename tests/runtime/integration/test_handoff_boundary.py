"""FP-AGT-004: Handoff 不跨审批/执行边界（Handoff 路径与拒绝事件）。

A handoff is a read-phase transfer: it is allowed while the task is still
gathering context (QUEUED / RUNNING before any attempt / WAITING_USER),
and refused once the task owns an approval card (WAITING_APPROVAL) or has
consumed execution authority (an attempt ran or a retry is pending).  Every
refusal is recorded as an audit event.
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
    ContextError,
    ContextErrorCode,
    ContextPolicy,
)
from flowpilot_domain import TaskCommand
from flowpilot_graph import (
    GraphNode,
    GraphState,
    GraphStatus,
    HandoffDecision,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)


def _state(
    *,
    status: GraphStatus,
    node: GraphNode,
    attempt_count: int = 0,
    command_id: str = "cmd_12345678",
) -> GraphState:
    return GraphState(
        task_id="task_12345678",
        tenant_id="tenant-a",
        command_id=command_id,
        command_digest="sha256:" + "0" * 64,
        run_id="run_12345678",
        run_generation=1,
        graph_version="graph-v1",
        status=status,
        node=node,
        security_context_ref="security-context://tenant-a/12345678",
        security_context_hash="sha256:" + "1" * 64,
        purpose="it_support",
        attempt_count=attempt_count,
    )


def _kernel(
    *,
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
    on_escalation: Callable[[object], None] | None = None,
) -> tuple[
    RuntimeGraphKernel, InMemoryLeaseStore, InMemoryCheckpointStore
]:
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    kernel = RuntimeGraphKernel(
        config=RuntimeGraphConfig(
            graph_version="graph-v1",
            context_policy=context_policy,
            agent=agent_profile,
            provider=provider_selection,
            budget=runtime_budget,
            on_escalation=on_escalation,
        ),
        context_builder=ContextBuilder(clock=fixed_clock),
        runtime=FakeAgentRuntime(clock=fixed_clock),
        checkpoints=checkpoints,
        clock=fixed_clock,
    )
    return kernel, leases, checkpoints


def test_handoff_allowed_in_read_phases(
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    kernel, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )

    for state in (
        _state(status=GraphStatus.QUEUED, node=GraphNode.START),
        _state(status=GraphStatus.RUNNING, node=GraphNode.BUILD_CONTEXT),
        _state(status=GraphStatus.WAITING_USER, node=GraphNode.INTERRUPT),
    ):
        decision = kernel.evaluate_handoff(
            state, target_agent_id="response-agent"
        )
        assert decision.allowed is True, state.status.value
        assert decision.boundary is None
        assert kernel.escalation_events == []


def test_handoff_refused_across_approval_boundary_with_audit_event(
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    received: list[object] = []
    kernel, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
        on_escalation=received.append,
    )
    state = _state(
        status=GraphStatus.WAITING_APPROVAL,
        node=GraphNode.INTERRUPT,
    )

    decision = kernel.evaluate_handoff(
        state, target_agent_id="response-agent"
    )

    assert decision.allowed is False
    assert decision.boundary == "approval"
    assert decision.reason
    # The refusal is an audit event: correlated, blocked, and safe.
    event = decision.audit_event
    assert event is not None
    assert event["event_type"] == "handoff_denied"
    assert event["boundary"] == "approval"
    assert event["result"] == "blocked"
    assert event["tenant_id"] == "tenant-a"
    assert event["task_id"] == "task_12345678"
    assert event["correlation_id"] == state.command_id
    assert event["target_agent_id"] == "response-agent"
    assert event["event_id"].startswith("evt_")
    # The sink receives the same event; the trail is append-only.
    assert received == [event]
    assert kernel.escalation_events == [event]
    # No sensitive fields leak into the audit payload.
    serialized = str(event).lower()
    for forbidden in ("approval_id", "credential", "session_ref"):
        assert forbidden not in serialized


def test_handoff_refused_across_execution_boundary(
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    kernel, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )

    for state in (
        # An attempt already ran.
        _state(
            status=GraphStatus.RETRY_PENDING,
            node=GraphNode.RUN_AGENT,
            attempt_count=1,
        ),
        # Execution is in flight.
        _state(
            status=GraphStatus.RUNNING,
            node=GraphNode.RUN_AGENT,
            attempt_count=1,
        ),
        # A finished attempt without retry state is still execution-owned.
        _state(
            status=GraphStatus.RUNNING,
            node=GraphNode.FINALIZE,
            attempt_count=2,
        ),
    ):
        decision: HandoffDecision = kernel.evaluate_handoff(
            state, target_agent_id="response-agent"
        )
        assert decision.allowed is False, state.status.value
        assert decision.boundary == "execution"
        assert decision.audit_event is not None

    assert len(kernel.escalation_events) == 3


def test_handoff_to_self_is_refused_without_audit(
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    kernel, _, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )
    state = _state(status=GraphStatus.RUNNING, node=GraphNode.BUILD_CONTEXT)

    decision = kernel.evaluate_handoff(
        state, target_agent_id=agent_profile.id
    )

    assert decision.allowed is False
    assert decision.boundary == "identity"
    assert kernel.escalation_events == []


def test_rebuild_handoff_denied_at_approval_boundary_raises(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    kernel, leases, _ = _kernel(
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
        fixed_clock=fixed_clock,
    )
    command = command_factory()
    lease = asyncio.run(
        leases.acquire(
            command.tenant_id, command.task_id, run_id="run_12345678"
        )
    )
    prepared = asyncio.run(
        kernel.prepare(command, execution_ref="exec_ref_1", lease=lease)
    )
    assert prepared.request is not None
    # Park the task at the approval boundary (the gate reads the state).
    approval_state = prepared.state.transition(
        GraphStatus.WAITING_APPROVAL,
        node=GraphNode.INTERRUPT,
        pending_reason="approval:apr_1",
    )

    with pytest.raises(ContextError) as captured:
        kernel.rebuild_handoff(
            state=approval_state,
            source=prepared.request.context,
            security_context=command.security_context,
            target_agent=AgentProfile(
                id="response-agent",
                version="1.0.0",
                prompt_version="prompt-v1",
                mode=agent_profile.mode,
                output_schema=agent_profile.output_schema,
                allowed_tools=agent_profile.allowed_tools,
                maximum_handoffs=0,
            ),
            required_task_fields=("status",),
            proposed_tools=(),
        )

    assert captured.value.code is ContextErrorCode.HANDOFF_DENIED
    assert kernel.escalation_events[-1]["boundary"] == "approval"
