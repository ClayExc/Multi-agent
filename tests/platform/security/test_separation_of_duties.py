"""FP-APR-001 / FP-APR-002 / FP-SEC-007 — approval binding, duties and audience.

Black-box Gateway security assertions for the write vertical slice:
- parameter tampering after approval invalidates the ``action_digest``
  binding and the write is blocked (FP-APR-001);
- an approver who no longer holds a required role cannot execute an approval
  and the block is retained as an audit/security pair (FP-APR-002);
- approval records cannot be replayed for another actor or action;
- a workload presenting the wrong audience is rejected (FP-SEC-007);
- cross-tenant writes stay at zero (architecture invariant 12).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from factories import OTHER_TENANT, WriteAdapter, make_fixture
from flowpilot_policy import PolicyDecisionKind
from flowpilot_tool_contracts import ToolResultStatus


async def ledger_record(fixture, execution_id: str):
    async with fixture.data_uow() as uow:
        return await uow.ledger.get(
            fixture.invocation.request.security_context.tenant_id,
            execution_id,
        )


@pytest.mark.asyncio
async def test_tampered_arguments_after_approval_are_blocked_without_write() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    tampered = replace(
        fixture.action,
        arguments={"ticket_id": "TCK-100", "status": "in_progress"},
    )
    fixture.replace_policy_for_action(tampered)
    invocation = fixture.replace_invocation(action=tampered)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code in {
        "PLATFORM_APPROVAL_INVALID",
        "PLATFORM_APPROVAL_BINDING_MISMATCH",
    }
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security) == 1
    assert fixture.signals.security[0].category == "approval_integrity"
    assert fixture.signals.audits[0].security_event_id == (
        fixture.signals.security[0].event_id
    )


@pytest.mark.asyncio
async def test_tampered_policy_decision_is_blocked_before_upstream() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    tampered = replace(
        fixture.action,
        arguments={"ticket_id": "TCK-100", "status": "in_progress"},
    )
    invocation = fixture.replace_invocation(action=tampered)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_POLICY_BINDING_MISMATCH"
    assert fixture.adapter.invocation_count == 0
    assert len(fixture.signals.security) == 1


@pytest.mark.asyncio
async def test_approver_without_current_role_is_blocked_and_audited() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.approvers.authorized = False

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_SEPARATION_OF_DUTIES"
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security) == 1
    security = fixture.signals.security[0]
    assert security.category == "approval_integrity"
    assert security.reason_codes == ("PLATFORM_SEPARATION_OF_DUTIES",)
    assert security.audit_event_id == fixture.signals.audits[0].event_id


@pytest.mark.asyncio
async def test_approval_replayed_for_another_actor_is_blocked() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    replayed = replace(
        fixture.approval,
        requester_id="user-mallory",
    )
    fixture.approval_source.approval = replayed

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_APPROVAL_INVALID"
    assert fixture.adapter.invocation_count == 0
    assert len(fixture.signals.security) == 1
    assert fixture.signals.security[0].category == "approval_integrity"


@pytest.mark.asyncio
async def test_approval_replayed_for_another_action_is_blocked() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    other_action = replace(
        fixture.action,
        action_id="act_other0001",
    )
    fixture.replace_policy_for_action(other_action)
    invocation = fixture.replace_invocation(action=other_action)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_APPROVAL_INVALID"
    assert fixture.adapter.invocation_count == 0
    assert len(fixture.signals.security) == 1


@pytest.mark.asyncio
async def test_wrong_audience_workload_is_rejected_before_write() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    forged_workload = replace(
        fixture.invocation.workload,
        audience="mcp://evil-gateway",
    )
    invocation = fixture.replace_invocation(workload=forged_workload)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_AUDIENCE_MISMATCH"
    assert fixture.adapter.invocation_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None


@pytest.mark.asyncio
async def test_cross_tenant_write_stays_at_zero() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    forged_action = replace(fixture.action, tenant_id=OTHER_TENANT)
    invocation = fixture.replace_invocation(action=forged_action)

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_TENANT_MISMATCH"
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    assert len(fixture.signals.security) == 1
    assert fixture.signals.security[0].category == "tenant_isolation"


@pytest.mark.asyncio
async def test_approval_cannot_be_attached_to_a_policy_that_does_not_require_it() -> (
    None
):
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    invocation = fixture.replace_invocation(
        approval_id=fixture.approval.approval_id
        if fixture.approval is not None
        else "apr_attached0001"
    )

    execution = await fixture.gateway.execute(invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_APPROVAL_INVALID"
    assert fixture.adapter.invocation_count == 0
    assert len(fixture.signals.security) == 1
