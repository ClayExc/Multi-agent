from __future__ import annotations

from dataclasses import replace

import pytest
from flowpilot_mcp_gateway import GatewayReason
from flowpilot_persistence import LedgerStatus
from flowpilot_tool_contracts import ToolResultStatus

from .blackbox import make_blackbox


@pytest.mark.asyncio
async def test_verified_write_replay_survives_gateway_restart() -> None:
    fixture = make_blackbox()

    first = await fixture.gateway.execute(fixture.invocation)
    fixture.restart_gateway()
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
    assert len(await fixture.outbox()) == 1


@pytest.mark.asyncio
async def test_unknown_is_not_blindly_retried_and_can_reconcile() -> None:
    fixture = make_blackbox()
    fixture.adapter.mode = "unknown_executed"

    unknown = await fixture.gateway.execute(fixture.invocation)
    duplicate = await fixture.gateway.execute(fixture.invocation)

    assert unknown.result.status is ToolResultStatus.UNKNOWN
    assert duplicate.result.status is ToolResultStatus.UNKNOWN
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await fixture.ledger_record(unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN

    recovered = await fixture.gateway.reconcile(fixture.invocation)
    assert recovered.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.reconciliation_count == 1
    record = await fixture.ledger_record(unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED


@pytest.mark.asyncio
async def test_authoritative_not_executed_proof_allows_one_safe_retry() -> None:
    fixture = make_blackbox()
    fixture.adapter.mode = "unknown_not_executed"

    unknown = await fixture.gateway.execute(fixture.invocation)
    reconciled = await fixture.gateway.reconcile(fixture.invocation)

    assert unknown.result.status is ToolResultStatus.UNKNOWN
    assert reconciled.result.status is ToolResultStatus.FAILED_RETRYABLE
    assert reconciled.result.retry_basis is not None
    assert reconciled.result.retry_basis.value == "confirmed_not_executed"
    assert reconciled.result.evidence_ref is not None
    fixture.adapter.mode = "verified"

    retried = await fixture.gateway.execute(fixture.invocation)
    assert retried.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 2
    assert fixture.adapter.logical_write_count == 1
    record = await fixture.ledger_record(unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert record.attempt_count == 2


@pytest.mark.asyncio
async def test_readback_mismatch_keeps_write_unknown() -> None:
    fixture = make_blackbox()
    fixture.adapter.mode = "readback_mismatch"

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.UNKNOWN
    assert execution.result.error_code == GatewayReason.READBACK_MISMATCH.value
    assert fixture.adapter.logical_write_count == 1
    record = await fixture.ledger_record(execution.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN


@pytest.mark.asyncio
async def test_same_idempotency_key_cannot_switch_parameters() -> None:
    fixture = make_blackbox()
    first = await fixture.gateway.execute(fixture.invocation)
    changed_action = replace(
        fixture.action,
        arguments={"ticket_id": "TCK-030", "status": "in_progress"},
    )
    fixture.bind_policy(changed_action)
    changed = fixture.request_for(action=changed_action)

    conflict = await fixture.gateway.execute(changed)

    assert first.result.status is ToolResultStatus.VERIFIED
    assert conflict.result.error_code == GatewayReason.IDEMPOTENCY_CONFLICT.value
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    assert len(fixture.signals.security_events) == 1


@pytest.mark.asyncio
async def test_not_sent_failure_is_retryable_without_claiming_execution() -> None:
    fixture = make_blackbox()
    fixture.adapter.mode = "not_sent"

    not_sent = await fixture.gateway.execute(fixture.invocation)

    assert not_sent.result.status is ToolResultStatus.FAILED_RETRYABLE
    assert not_sent.result.retry_basis is not None
    assert not_sent.result.retry_basis.value == "not_sent"
    assert fixture.adapter.logical_write_count == 0
    fixture.adapter.mode = "verified"

    retried = await fixture.gateway.execute(fixture.invocation)
    assert retried.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 2
    assert fixture.adapter.logical_write_count == 1
