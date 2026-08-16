from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from flowpilot_domain import ActionTool, ApprovalStatus, ToolOperation, canonical_sha256
from flowpilot_mcp_gateway import GatewayReason
from flowpilot_policy import (
    PolicyDecision,
    PolicyDecisionKind,
    PolicyError,
    PolicyErrorCode,
)
from flowpilot_tool_contracts import AgentPrincipal, ToolRequest, ToolResultStatus

from packages.evaluation.reporting import CaseStatus
from packages.evaluation.scoring import DeterministicScorer

from .blackbox import (
    AGENT_PRINCIPAL,
    AGENT_VERSION,
    AUDIENCE,
    NOW,
    OTHER_TENANT,
    bind_context_snapshot,
    make_blackbox,
)


async def assert_rejected_before_side_effect(
    fixture,
    invocation,
    expected_code: str,
) -> None:
    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == expected_code
    assert fixture.adapter.invocation_count == 0
    assert await fixture.ledger_record(execution.result.execution_id) is None
    assert await fixture.outbox() == ()
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security_events) == 1


@pytest.mark.asyncio
async def test_dual_principal_agent_forgery_is_rejected() -> None:
    fixture = make_blackbox()
    forged = AgentPrincipal(
        id="forged-agent",
        version=AGENT_VERSION,
        principal_ref=AGENT_PRINCIPAL,
    )

    await assert_rejected_before_side_effect(
        fixture,
        fixture.request_for(declared_agent=forged),
        "PLATFORM_AGENT_MISMATCH",
    )


@pytest.mark.asyncio
async def test_cross_tenant_action_is_rejected() -> None:
    fixture = make_blackbox()
    action = replace(fixture.action, tenant_id=OTHER_TENANT)

    await assert_rejected_before_side_effect(
        fixture,
        fixture.request_for(action=action),
        "PLATFORM_TENANT_MISMATCH",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("purpose", "PLATFORM_PURPOSE_DENIED"),
        ("audience", "PLATFORM_AUDIENCE_MISMATCH"),
    ],
)
async def test_purpose_and_audience_are_server_bound(
    mutation: str,
    expected_code: str,
) -> None:
    fixture = make_blackbox()
    if mutation == "purpose":
        action = replace(fixture.action, purpose="unapproved-purpose")
        fixture.bind_policy(action)
        invocation = fixture.request_for(action=action)
    else:
        workload = replace(
            fixture.invocation.workload,
            audience=AUDIENCE + "/forged",
        )
        invocation = fixture.request_for(workload=workload)

    await assert_rejected_before_side_effect(
        fixture,
        invocation,
        expected_code,
    )


@pytest.mark.asyncio
async def test_expired_context_is_rejected() -> None:
    fixture = make_blackbox()
    expired = bind_context_snapshot(
        replace(
            fixture.invocation.request.security_context,
            expires_at=NOW - timedelta(seconds=1),
        )
    )
    fixture.context_source.context = expired
    request_mapping = fixture.invocation.request.to_mapping()
    request_mapping["security_context"] = expired.to_mapping()
    request = ToolRequest.from_mapping(request_mapping)
    invocation = replace(fixture.invocation, request=request)

    await assert_rejected_before_side_effect(
        fixture,
        invocation,
        "PLATFORM_SECURITY_CONTEXT_EXPIRED",
    )


@pytest.mark.asyncio
async def test_unregistered_tool_bypass_is_default_denied() -> None:
    fixture = make_blackbox()
    action = replace(
        fixture.action,
        tool=ActionTool(
            name="acceptance.bypass.write.v1",
            schema_hash=fixture.action.tool.schema_hash,
            operation=ToolOperation.WRITE,
        ),
    )

    await assert_rejected_before_side_effect(
        fixture,
        fixture.request_for(action=action),
        GatewayReason.TOOL_NOT_REGISTERED.value,
    )


@pytest.mark.asyncio
async def test_policy_unavailable_fails_closed() -> None:
    fixture = make_blackbox()
    fixture.policy_source.available = False

    await assert_rejected_before_side_effect(
        fixture,
        fixture.invocation,
        "PLATFORM_POLICY_UNAVAILABLE",
    )


def test_unknown_and_conflicting_obligations_fail_closed() -> None:
    fixture = make_blackbox()
    unknown = fixture.policy.to_mapping()
    unknown["obligations"] = [
        {"name": "model_override", "parameters": {}},
    ]
    duplicate = fixture.policy.to_mapping()
    duplicate["obligations"] = [
        {"name": "audit_level", "parameters": {"level": "standard"}},
        {"name": "audit_level", "parameters": {"level": "security"}},
    ]

    for mapping, expected in (
        (unknown, PolicyErrorCode.OBLIGATION_UNSUPPORTED),
        (duplicate, PolicyErrorCode.OBLIGATION_CONFLICT),
    ):
        with pytest.raises(PolicyError) as captured:
            PolicyDecision.from_mapping(mapping)
        assert captured.value.code is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "action_digest",
        "tool_schema_hash",
        "policy_version",
        "requester_id",
        "tenant_id",
        "expires_at",
    ],
)
async def test_approval_binding_tamper_is_rejected(field: str) -> None:
    fixture = make_blackbox(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    assert fixture.approval is not None
    if field == "action_digest":
        changed = replace(
            fixture.approval,
            action_digest=canonical_sha256({"forged": "action"}),
        )
    elif field == "tool_schema_hash":
        changed = replace(
            fixture.approval,
            tool_schema_hash=canonical_sha256({"forged": "schema"}),
        )
    elif field == "policy_version":
        changed = replace(
            fixture.approval,
            policy_version="policy-forged",
        )
    elif field == "requester_id":
        changed = replace(
            fixture.approval,
            requester_id="user-forged",
        )
    elif field == "tenant_id":
        changed = replace(
            fixture.approval,
            tenant_id=OTHER_TENANT,
        )
    else:
        changed = replace(
            fixture.approval,
            expires_at=fixture.approval.expires_at - timedelta(seconds=1),
        )
    fixture.approval_source.approval = changed

    await assert_rejected_before_side_effect(
        fixture,
        fixture.invocation,
        "PLATFORM_APPROVAL_INVALID",
    )


@pytest.mark.asyncio
async def test_expired_approval_and_role_forgery_are_rejected() -> None:
    expired_fixture = make_blackbox(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    assert expired_fixture.approval is not None
    expired_fixture.approval_source.approval = replace(
        expired_fixture.approval,
        status=ApprovalStatus.APPROVED,
        expires_at=NOW,
    )
    expired = await expired_fixture.gateway.execute(
        expired_fixture.invocation
    )
    assert expired.result.error_code == "PLATFORM_APPROVAL_EXPIRED"
    assert expired_fixture.adapter.invocation_count == 0

    role_fixture = make_blackbox(
        decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL
    )
    role_fixture.approvers.role_granted = False
    forged_role = await role_fixture.gateway.execute(role_fixture.invocation)
    assert forged_role.result.error_code == "PLATFORM_SEPARATION_OF_DUTIES"
    assert role_fixture.adapter.invocation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_mode", "expected_code"),
    [
        ("malicious_extra_field", "PLATFORM_TOOL_OUTPUT_INVALID"),
        ("secret_material", "PLATFORM_DLP_BLOCKED"),
    ],
)
async def test_malicious_or_secret_tool_output_is_not_projected(
    adapter_mode: str,
    expected_code: str,
) -> None:
    fixture = make_blackbox(operation=ToolOperation.READ)
    fixture.adapter.mode = adapter_mode

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == expected_code
    assert execution.result.data is None
    assert fixture.adapter.invocation_count == 1
    assert len(fixture.signals.security_events) == 1
    serialized = json.dumps(
        {
            "result": execution.result.to_mapping(),
            "projection": dict(execution.debug_projection),
            "lifecycle": [
                event.to_mapping() for event in execution.lifecycle
            ],
            "audits": [
                event.to_mapping() for event in fixture.signals.audits
            ],
            "security": [
                event.to_mapping()
                for event in fixture.signals.security_events
            ],
        },
        sort_keys=True,
    ).casefold()
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "password=acceptance-secret" not in serialized


@pytest.mark.asyncio
async def test_deterministic_gateway_failure_cannot_be_overridden_by_judge() -> None:
    fixture = make_blackbox()
    fixture.policy_source.available = False
    execution = await fixture.gateway.execute(fixture.invocation)
    registry = json.loads(
        Path("contracts/registries/evaluation-registry.v1.json").read_text(
            encoding="utf-8"
        )
    )
    scorer = DeterministicScorer.from_registry(registry)

    result = scorer.score(
        case_id="case_platform_failure_001",
        suite="functional",
        category="platform-security",
        execution_status=(
            CaseStatus.FAILED
            if execution.result.status is not ToolResultStatus.VERIFIED
            else CaseStatus.PASSED
        ),
        assertion_results={"assert.secret.exposure_zero.v1": True},
        judge_scores={"judge.semantic.answer_relevance.v1": 1.0},
    )

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert result.status is CaseStatus.FAILED
    assert result.judge_scores == {
        "judge.semantic.answer_relevance.v1": 1.0
    }
