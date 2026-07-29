from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

import pytest
from flowpilot_context import (
    ContextBuilder,
    ContextBuildRequest,
    ContextError,
    ContextErrorCode,
    ContextLayer,
    ContextPolicy,
    LayerName,
    TrustLevel,
)
from flowpilot_domain import DataClassification, TaskCommand


def _build_request(
    command: TaskCommand,
    policy: ContextPolicy,
    *,
    optional_layers: tuple[ContextLayer, ...] = (),
) -> ContextBuildRequest:
    return ContextBuildRequest(
        context_id="ctx_12345678",
        task_id=command.task_id,
        agent_id="knowledge-agent",
        purpose=command.security_context.purpose,
        security_context=command.security_context,
        task_state={"status": "RUNNING", "intent": "knowledge_question"},
        task_state_ref=f"task://{command.task_id}/v1",
        system_policy_ref="policy://runtime/v1",
        policy=policy,
        optional_layers=optional_layers,
    )


def test_minimum_context_has_exact_required_layers(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    envelope = ContextBuilder(clock=fixed_clock).build(
        _build_request(command_factory(), context_policy)
    )

    assert [layer.name for layer in envelope.layers] == [
        LayerName.SYSTEM_POLICY,
        LayerName.SECURITY_VIEW,
        LayerName.TASK_STATE,
    ]
    assert envelope.tenant_id == "tenant-a"
    assert envelope.manifest.input_tokens_estimated <= context_policy.token_budget
    assert "credential" in envelope.manifest.excluded_fields


def test_exact_hard_budget_is_accepted_and_optional_data_is_trimmed(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    builder = ContextBuilder(clock=fixed_clock)
    command = command_factory()
    baseline = builder.build(_build_request(command, context_policy))
    exact_policy = replace(
        context_policy,
        token_budget=baseline.manifest.input_tokens_estimated,
    )
    optional = ContextLayer(
        name=LayerName.RECENT_MESSAGES,
        trust=TrustLevel.UNTRUSTED_DATA,
        classification=DataClassification.INTERNAL,
        content={"messages": ["external text " * 200]},
        source_refs=("message://recent/1",),
    )

    envelope = builder.build(
        _build_request(command, exact_policy, optional_layers=(optional,))
    )

    assert len(envelope.layers) == 3
    assert envelope.manifest.input_tokens_estimated == exact_policy.token_budget
    assert envelope.manifest.truncation_reason == (
        "token_budget:L4_RECENT_MESSAGES"
    )


def test_required_context_over_budget_fails_closed(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    too_small = replace(context_policy, token_budget=1)

    with pytest.raises(ContextError) as captured:
        ContextBuilder(clock=fixed_clock).build(
            _build_request(command_factory(), too_small)
        )

    assert captured.value.code is ContextErrorCode.BUDGET_EXHAUSTED


def test_context_purpose_and_classification_bind_security_context(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    purpose_mismatch = replace(
        _build_request(command, context_policy),
        purpose="security_investigation",
    )
    excessive_policy = replace(
        context_policy,
        data_classification_ceiling=DataClassification.RESTRICTED,
    )

    with pytest.raises(ContextError) as purpose_error:
        ContextBuilder(clock=fixed_clock).build(purpose_mismatch)
    with pytest.raises(ContextError) as classification_error:
        ContextBuilder(clock=fixed_clock).build(
            _build_request(command, excessive_policy)
        )

    assert (
        purpose_error.value.code
        is ContextErrorCode.SECURITY_BINDING_MISMATCH
    )
    assert (
        classification_error.value.code
        is ContextErrorCode.CLASSIFICATION_DENIED
    )


def test_handoff_rebuilds_minimal_context_and_tool_scope(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    builder = ContextBuilder(clock=fixed_clock)
    source = builder.build(_build_request(command, context_policy))

    handoff = builder.rebuild_for_handoff(
        source=source,
        security_context=command.security_context,
        target_agent_id="response-agent",
        new_context_id="ctx_87654321",
        required_task_fields=("status",),
        allowed_tools=("knowledge.search.v1",),
    )

    assert handoff.context.agent_id == "response-agent"
    assert handoff.context.layer(LayerName.TASK_STATE).content == {
        "status": "RUNNING"
    }
    assert len(handoff.context.layers) == 3
    assert handoff.manifest.allowed_tools == ("knowledge.search.v1",)
    assert "tool_credentials" in handoff.manifest.excluded_categories


def test_handoff_cannot_request_approval_or_credentials(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    fixed_clock: Callable[[], datetime],
) -> None:
    command = command_factory()
    builder = ContextBuilder(clock=fixed_clock)
    source = builder.build(_build_request(command, context_policy))

    with pytest.raises(ContextError) as captured:
        builder.rebuild_for_handoff(
            source=source,
            security_context=command.security_context,
            target_agent_id="response-agent",
            new_context_id="ctx_87654321",
            required_task_fields=("approval_id",),
            allowed_tools=(),
        )

    assert captured.value.code is ContextErrorCode.HANDOFF_DENIED
