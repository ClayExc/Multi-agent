"""FP-CTX-003: Handoff 字段与工具重新过滤（Handoff Manifest）。

A handoff must never carry approval/credential/session/tool-credential
state and must never grant tools the target agent is not allowed to call.
The rebuilt bundle is minimal (only requested task fields), its manifest
records what was included/excluded, and a recursive leak scan over the
serialized bundle must report zero forbidden fields.
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
    ContextBuildRequest,
    ContextEnvelope,
    ContextError,
    ContextErrorCode,
    ContextPolicy,
    HandoffBundle,
    LayerName,
    forbidden_field_scan,
)
from flowpilot_domain import TaskCommand
from flowpilot_graph import (
    GraphNode,
    GraphState,
    GraphStatus,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)


def _source_envelope(
    builder: ContextBuilder,
    command: TaskCommand,
    policy: ContextPolicy,
) -> ContextEnvelope:
    return builder.build(
        ContextBuildRequest(
            context_id="ctx_12345678",
            task_id=command.task_id,
            agent_id="knowledge-agent",
            purpose=command.security_context.purpose,
            security_context=command.security_context,
            task_state={
                "status": "RUNNING",
                "intent": "vpn_escalation",
                "approval": {"card_id": "apr_1"},
                "session_ref": "session://provider/1",
                "tool_credentials": {"vpn_admin": "unused"},
            },
            task_state_ref=f"task://{command.task_id}/v1",
            system_policy_ref="policy://runtime/v1",
            policy=policy,
        )
    )


def test_handoff_tools_are_refiltered_against_target_allowlist(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    builder = ContextBuilder(clock=fixed_clock)
    source = _source_envelope(builder, command, context_policy)

    bundle = builder.rebuild_for_handoff(
        source=source,
        security_context=command.security_context,
        target_agent_id="response-agent",
        new_context_id="ctx_87654321",
        required_task_fields=("status", "intent"),
        allowed_tools=("knowledge.search.v1", "vpn.admin.write.v1"),
        target_tool_allowlist=("knowledge.search.v1",),
    )

    # The tool the target agent is not allowed to call is dropped.
    assert bundle.manifest.allowed_tools == ("knowledge.search.v1",)


def test_handoff_without_allowlist_passes_tools_through(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    builder = ContextBuilder(clock=fixed_clock)
    source = _source_envelope(builder, command, context_policy)

    bundle = builder.rebuild_for_handoff(
        source=source,
        security_context=command.security_context,
        target_agent_id="response-agent",
        new_context_id="ctx_87654321",
        required_task_fields=("status",),
        allowed_tools=("knowledge.search.v1", "vpn.admin.write.v1"),
    )

    assert bundle.manifest.allowed_tools == (
        "knowledge.search.v1",
        "vpn.admin.write.v1",
    )


def test_handoff_manifest_is_minimal_and_auditable(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    builder = ContextBuilder(clock=fixed_clock)
    source = _source_envelope(builder, command, context_policy)

    bundle = builder.rebuild_for_handoff(
        source=source,
        security_context=command.security_context,
        target_agent_id="response-agent",
        new_context_id="ctx_87654321",
        required_task_fields=("status", "intent"),
        allowed_tools=("knowledge.search.v1",),
    )

    # Only the requested fields ride along; the forbidden categories are
    # excluded and the leak scan over the serialized bundle is clean.
    assert bundle.context.layer(LayerName.TASK_STATE).content == {
        "status": "RUNNING",
        "intent": "vpn_escalation",
    }
    assert bundle.manifest.included_fields == ("task.status", "task.intent")
    assert set(bundle.manifest.excluded_categories) >= {
        "approval",
        "provider_session",
        "tool_credentials",
    }
    assert forbidden_field_scan(bundle.to_mapping()) == ()


def test_handoff_denies_requesting_forbidden_fields(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    builder = ContextBuilder(clock=fixed_clock)
    source = _source_envelope(builder, command, context_policy)

    for forbidden in (
        "approval",
        "approval_id",
        "credential",
        "credentials",
        "provider_session",
        "session_ref",
        "tool_credentials",
    ):
        with pytest.raises(ContextError) as captured:
            builder.rebuild_for_handoff(
                source=source,
                security_context=command.security_context,
                target_agent_id="response-agent",
                new_context_id="ctx_87654321",
                required_task_fields=(forbidden,),
                allowed_tools=(),
            )
        assert captured.value.code is ContextErrorCode.HANDOFF_DENIED


def test_kernel_rebuild_gate_applies_allowlist_and_leak_scan(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    """Kernel-level rebuild: boundary gate + allowlist + leak scan."""
    leases = InMemoryLeaseStore(clock=fixed_clock)
    checkpoints = InMemoryCheckpointStore(leases=leases)
    kernel = RuntimeGraphKernel(
        config=RuntimeGraphConfig(
            graph_version="graph-v1",
            context_policy=context_policy,
            agent=agent_profile,
            provider=provider_selection,
            budget=runtime_budget,
        ),
        context_builder=ContextBuilder(clock=fixed_clock),
        runtime=FakeAgentRuntime(clock=fixed_clock),
        checkpoints=checkpoints,
        clock=fixed_clock,
    )
    command = command_factory()
    lease = asyncio.run(
        leases.acquire(command.tenant_id, command.task_id, run_id="run_12345678")
    )
    prepared = asyncio.run(
        kernel.prepare(command, execution_ref="exec_ref_1", lease=lease)
    )
    assert prepared.request is not None
    source = prepared.request.context
    target_agent = AgentProfile(
        id="response-agent",
        version="1.0.0",
        prompt_version="prompt-v1",
        mode=agent_profile.mode,
        output_schema=agent_profile.output_schema,
        allowed_tools=agent_profile.allowed_tools,  # only knowledge.search.v1
        maximum_handoffs=0,
    )
    # Handoff happens in the read phase: rebuild the state as it was
    # before the task entered execution.
    read_phase_state = GraphState(
        task_id=command.task_id,
        tenant_id=command.tenant_id,
        command_id=command.command_id,
        command_digest=command.command_digest,
        run_id=lease.run_id,
        run_generation=lease.run_generation,
        graph_version="graph-v1",
        status=GraphStatus.RUNNING,
        node=GraphNode.BUILD_CONTEXT,
        security_context_ref=command.security_context.context_ref,
        security_context_hash=command.security_context.context_hash,
        purpose=command.security_context.purpose,
    )

    bundle = kernel.rebuild_handoff(
        state=read_phase_state,
        source=source,
        security_context=command.security_context,
        target_agent=target_agent,
        required_task_fields=("status",),
        proposed_tools=("knowledge.search.v1", "vpn.admin.write.v1"),
    )

    assert isinstance(bundle, HandoffBundle)
    assert bundle.context.agent_id == "response-agent"
    assert bundle.manifest.allowed_tools == ("knowledge.search.v1",)
    assert forbidden_field_scan(bundle.to_mapping()) == ()
