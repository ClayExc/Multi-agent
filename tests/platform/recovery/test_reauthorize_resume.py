"""FP-APR-003 — permission revocation invalidates old approvals on resume.

Black-box Gateway recovery assertions:
- removing the approver's role after approval blocks execution and the
  refusal is retained as an audit/security pair;
- a record-level revocation (status ``revoked``) invalidates the approval;
- an expired approval can never authorize a write;
- re-authorization with a fresh valid approval resumes the write path.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from factories import (
    APPROVER,
    NOW,
    SUBJECT,
    WriteAdapter,
    make_fixture,
)
from flowpilot_domain import ApprovalStatus
from flowpilot_policy import PolicyDecisionKind
from flowpilot_tool_contracts import ToolResultStatus


async def ledger_record(fixture, execution_id: str):
    async with fixture.data_uow() as uow:
        return await uow.ledger.get(
            fixture.invocation.request.security_context.tenant_id,
            execution_id,
        )


@pytest.mark.asyncio
async def test_role_revocation_after_approval_blocks_resume_with_audit() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.approvers.authorized = False

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_SEPARATION_OF_DUTIES"
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0
    assert await ledger_record(fixture, execution.result.execution_id) is None
    # The refusal is retained: audit + security event pair.
    assert len(fixture.signals.audits) == 1
    assert len(fixture.signals.security) == 1
    audit = fixture.signals.audits[0]
    security = fixture.signals.security[0]
    assert audit.event_type == "audit.authorization.denied.v1"
    assert audit.security_event_id == security.event_id
    assert audit.action_digest == fixture.invocation.request.action_digest
    assert audit.policy_decision_id == fixture.policy.decision_id
    assert security.category == "approval_integrity"


@pytest.mark.asyncio
async def test_revoked_approval_record_is_invalid_on_resume() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    revoked = replace(
        fixture.approval,
        status=ApprovalStatus.REVOKED,
        decision_reason="approver role revoked",
        decided_at=NOW - timedelta(minutes=1),
    )
    fixture.approval_source.approval = revoked

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_APPROVAL_REQUIRED"
    assert fixture.adapter.invocation_count == 0
    assert len(fixture.signals.security) == 1


@pytest.mark.asyncio
async def test_expired_approval_is_rejected_on_resume() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    expired = replace(
        fixture.approval,
        requested_at=NOW - timedelta(minutes=3),
        decided_at=NOW - timedelta(minutes=2),
        expires_at=NOW - timedelta(minutes=1),
    )
    fixture.approval_source.approval = expired

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == "PLATFORM_APPROVAL_EXPIRED"
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0


@pytest.mark.asyncio
async def test_reauthorized_approval_resumes_the_write_path() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.approvers.authorized = False
    blocked = await fixture.gateway.execute(fixture.invocation)
    assert blocked.result.status is ToolResultStatus.FAILED_FINAL

    # The approver is re-authorized and a fresh approval is granted.
    fixture.approvers.authorized = True
    fresh = replace(
        fixture.approval,
        approval_id="apr_alpha0002",
        status=ApprovalStatus.APPROVED,
        approver_id=APPROVER,
        requester_id=SUBJECT,
        decided_at=NOW - timedelta(minutes=1),
        expires_at=fixture.action.expires_at,
    )
    fixture.approval_source.approval = fresh
    resumed = await fixture.gateway.execute(
        fixture.replace_invocation(approval_id=fresh.approval_id)
    )

    assert resumed.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await ledger_record(fixture, resumed.result.execution_id)
    assert record is not None
    assert record.status.value == "verified"
    assert record.intent.approval_id == fresh.approval_id
