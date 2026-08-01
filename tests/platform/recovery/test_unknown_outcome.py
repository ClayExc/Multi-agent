"""FP-MCP-005 — ``UNKNOWN`` outcomes reconcile before any retry.

Black-box Gateway recovery assertions:
- a write timeout whose upstream actually executed stays ``UNKNOWN`` and is
  never blindly re-invoked;
- reconciliation against the upstream idempotency lookup either verifies the
  existing resource (0 duplicate creations) or authoritatively proves the
  write was not executed and unlocks exactly one retry;
- reconciliation is a write-only protocol.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from factories import NOW, WriteAdapter, make_fixture
from flowpilot_domain import ToolOperation
from flowpilot_mcp_gateway import GatewayReason
from flowpilot_persistence import LedgerStatus
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
async def test_timeout_but_executed_is_unknown_and_reconcile_verifies_no_duplicate() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "unknown_executed"

    first = await fixture.gateway.execute(fixture.invocation)
    replay = await fixture.gateway.execute(fixture.invocation)

    assert first.result.status is ToolResultStatus.UNKNOWN
    assert first.result.reconciliation is not None
    assert first.result.reconciliation.state == "pending"
    assert first.result.reconciliation.next_action == "reconcile_only"
    assert replay.result.status is ToolResultStatus.UNKNOWN
    # No blind retry: the upstream was invoked exactly once.
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1

    recovered = await fixture.gateway.reconcile(fixture.invocation)

    assert recovered.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await ledger_record(fixture, first.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED


@pytest.mark.asyncio
async def test_timeout_not_executed_reconciles_then_retries_exactly_once() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "unknown_not_executed"

    unknown = await fixture.gateway.execute(fixture.invocation)
    reconciled = await fixture.gateway.reconcile(fixture.invocation)

    assert unknown.result.status is ToolResultStatus.UNKNOWN
    assert reconciled.result.status is ToolResultStatus.FAILED_RETRYABLE
    assert reconciled.result.retry_basis is not None
    assert reconciled.result.retry_basis.value == "confirmed_not_executed"
    assert reconciled.result.verification is not None
    assert reconciled.result.verification.matched is False
    assert fixture.adapter.logical_write_count == 0
    fixture.adapter.mode = "verified"

    retried = await fixture.gateway.execute(fixture.invocation)

    assert retried.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 2
    assert fixture.adapter.logical_write_count == 1
    record = await ledger_record(fixture, unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert record.attempt_count == 2


@pytest.mark.asyncio
async def test_unknown_never_duplicates_without_reconciliation() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "unknown_executed"

    first = await fixture.gateway.execute(fixture.invocation)
    for _ in range(5):
        replay = await fixture.gateway.execute(fixture.invocation)

    assert first.result.status is ToolResultStatus.UNKNOWN
    assert replay.result.status is ToolResultStatus.UNKNOWN
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await ledger_record(fixture, first.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_only_applies_to_write_executions() -> None:
    fixture = make_fixture(operation=ToolOperation.READ)

    execution = await fixture.gateway.reconcile(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert (
        execution.result.error_code == GatewayReason.RECONCILIATION_REQUIRED.value
    )
    assert len(await outbox_items(fixture)) == 0
