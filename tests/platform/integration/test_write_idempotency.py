"""FP-MCP-003 / FP-MCP-004 — write idempotency and readback verification.

Black-box Gateway assertions for the write vertical slice:
- the same execution command replayed ten times produces exactly one
  upstream resource (FP-MCP-003);
- the write outcome reaches ``VERIFIED`` only through authoritative readback
  and the ledger/outbox/audit are complete (FP-MCP-004);
- the audit event correlates task, policy, action digest, approval,
  execution and result.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from factories import NOW, WriteAdapter, make_fixture
from flowpilot_mcp_gateway import GatewayReason
from flowpilot_persistence import LedgerStatus
from flowpilot_policy import PolicyDecisionKind
from flowpilot_tool_contracts import ToolResultStatus


async def ledger_record(fixture, execution_id: str):
    async with fixture.data_uow() as uow:
        return await uow.ledger.get(
            fixture.invocation.request.security_context.tenant_id,
            execution_id,
        )


async def outbox_items(fixture):
    async with fixture.data_uow() as uow:
        return await uow.outbox.unpublished(
            fixture.invocation.request.security_context.tenant_id,
            now=NOW + timedelta(days=1),
            limit=100,
        )


@pytest.mark.asyncio
async def test_approved_write_reaches_verified_with_complete_audit_correlation() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    assert execution.result.verification is not None
    assert execution.result.verification.method.value == "read_back"
    assert execution.result.verification.matched is True
    assert execution.result.evidence_ref == "evidence://ticket/readback"

    record = await ledger_record(fixture, execution.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert record.intent.approval_id == fixture.approval.approval_id
    assert record.intent.action_digest == fixture.invocation.request.action_digest
    assert record.intent.policy_decision_id == fixture.policy.decision_id
    assert len(await outbox_items(fixture)) == 1

    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1

    # Audit correlation: one audit event carries task, policy, action digest,
    # approval, execution id and result (AC-E2E-001 audit assertion).
    assert len(fixture.signals.audits) == 1
    audit = fixture.signals.audits[0]
    assert audit.event_type == "audit.tool.verified.v1"
    assert audit.task_id == fixture.invocation.request.planned_action.task_id
    assert audit.policy_decision_id == fixture.policy.decision_id
    assert audit.action_digest == fixture.invocation.request.action_digest
    assert audit.approval_id == fixture.approval.approval_id
    assert audit.tool_execution_id == execution.result.execution_id
    assert audit.result == "success"
    assert fixture.signals.security == []


@pytest.mark.asyncio
async def test_same_write_command_replayed_ten_times_creates_one_resource() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)

    first = None
    for _ in range(10):
        first = await fixture.gateway.execute(fixture.invocation)

    assert first is not None
    assert first.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await ledger_record(fixture, first.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert record.attempt_count == 1
    assert len(await outbox_items(fixture)) == 1
    assert len(fixture.signals.audits) == 1


@pytest.mark.asyncio
async def test_replayed_write_after_approval_does_not_repeat_upstream_call() -> None:
    fixture = make_fixture(decision_kind=PolicyDecisionKind.REQUIRE_APPROVAL)
    assert isinstance(fixture.adapter, WriteAdapter)

    first = await fixture.gateway.execute(fixture.invocation)
    replay = await fixture.gateway.execute(fixture.invocation)

    assert first.result.status is ToolResultStatus.VERIFIED
    assert replay.result.status is ToolResultStatus.VERIFIED
    assert replay.result.execution_id == first.result.execution_id
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    assert any(
        event.reason_code == GatewayReason.LEDGER_REPLAY.value
        for event in replay.lifecycle
    )
    assert len(await outbox_items(fixture)) == 1


@pytest.mark.asyncio
async def test_readback_mismatch_never_reports_verified() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "readback_mismatch"

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.UNKNOWN
    assert execution.result.error_code == GatewayReason.READBACK_MISMATCH.value
    assert fixture.adapter.logical_write_count == 1
    record = await ledger_record(fixture, execution.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN
