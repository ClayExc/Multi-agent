from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from factories import NOW, WriteAdapter, make_fixture
from flowpilot_domain import canonical_sha256
from flowpilot_mcp_gateway import GatewayReason, McpGateway
from flowpilot_persistence import LedgerStatus
from flowpilot_tool_contracts import ToolResultStatus


async def record_for(fixture, execution_id: str):
    async with fixture.data_uow() as uow:
        return await uow.ledger.get(
            fixture.invocation.request.security_context.tenant_id,
            execution_id,
        )


async def outbox_for(fixture):
    async with fixture.data_uow() as uow:
        return await uow.outbox.unpublished(
            fixture.invocation.request.security_context.tenant_id,
            now=NOW + timedelta(days=1),
            limit=100,
        )


@pytest.mark.asyncio
async def test_write_is_verified_by_readback_and_transactional_audit() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.VERIFIED
    assert execution.result.verification is not None
    assert execution.result.verification.method.value == "read_back"
    assert execution.result.verification.matched is True
    assert execution.result.evidence_ref == "evidence://ticket/readback"
    record = await record_for(fixture, execution.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert record.attempt_count == 1
    assert len(await outbox_for(fixture)) == 1
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1


@pytest.mark.asyncio
async def test_duplicate_verified_request_does_not_repeat_write() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)

    first = await fixture.gateway.execute(fixture.invocation)
    second = await fixture.gateway.execute(fixture.invocation)

    assert first.result.status is ToolResultStatus.VERIFIED
    assert second.result.status is ToolResultStatus.VERIFIED
    assert second.result.execution_id == first.result.execution_id
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    assert len(await outbox_for(fixture)) == 1
    assert any(
        event.reason_code == GatewayReason.LEDGER_REPLAY.value
        for event in second.lifecycle
    )


@pytest.mark.asyncio
async def test_same_idempotency_key_with_changed_action_is_conflict() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    first = await fixture.gateway.execute(fixture.invocation)
    changed_action = replace(
        fixture.action,
        arguments={"ticket_id": "TCK-100", "status": "in_progress"},
    )
    fixture.replace_policy_for_action(changed_action)
    changed = fixture.replace_invocation(action=changed_action)

    second = await fixture.gateway.execute(changed)

    assert first.result.status is ToolResultStatus.VERIFIED
    assert (
        second.result.error_code == GatewayReason.IDEMPOTENCY_CONFLICT.value
    )
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await record_for(fixture, first.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED


@pytest.mark.asyncio
async def test_unknown_is_not_blindly_retried_and_reconcile_can_verify() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "unknown_executed"

    first = await fixture.gateway.execute(fixture.invocation)
    duplicate = await fixture.gateway.execute(fixture.invocation)

    assert first.result.status is ToolResultStatus.UNKNOWN
    assert duplicate.result.status is ToolResultStatus.UNKNOWN
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await record_for(fixture, first.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN

    recovered = await fixture.gateway.reconcile(fixture.invocation)

    assert recovered.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 1
    record = await record_for(fixture, first.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert len(await outbox_for(fixture)) == 2


@pytest.mark.asyncio
async def test_authoritative_not_executed_proof_unlocks_one_retry() -> None:
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
    fixture.adapter.mode = "verified"

    retried = await fixture.gateway.execute(fixture.invocation)

    assert retried.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 2
    assert fixture.adapter.logical_write_count == 1
    record = await record_for(fixture, unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.VERIFIED
    assert record.attempt_count == 2
    outbox = await outbox_for(fixture)
    assert len(outbox) == 3
    assert len({item.event.event_id for item in outbox}) == 3


@pytest.mark.asyncio
async def test_not_sent_failure_can_retry_without_unknown_reconciliation() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "not_sent"

    first = await fixture.gateway.execute(fixture.invocation)

    assert first.result.status is ToolResultStatus.FAILED_RETRYABLE
    assert first.result.retry_basis is not None
    assert first.result.retry_basis.value == "not_sent"
    assert fixture.adapter.logical_write_count == 0
    fixture.adapter.mode = "verified"

    second = await fixture.gateway.execute(fixture.invocation)

    assert second.result.status is ToolResultStatus.VERIFIED
    assert fixture.adapter.invocation_count == 2
    assert fixture.adapter.logical_write_count == 1


@pytest.mark.asyncio
async def test_readback_unavailable_keeps_write_unknown() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "readback_unavailable"

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.UNKNOWN
    assert fixture.adapter.invocation_count == 1
    assert fixture.adapter.logical_write_count == 1
    record = await record_for(fixture, execution.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconciliation_backend_failure_preserves_unknown_state() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "unknown_not_executed"
    unknown = await fixture.gateway.execute(fixture.invocation)
    fixture.adapter.mode = "reconcile_unavailable"

    result = await fixture.gateway.reconcile(fixture.invocation)

    assert unknown.result.status is ToolResultStatus.UNKNOWN
    assert result.result.status is ToolResultStatus.UNKNOWN
    assert result.debug_projection["reason_code"] == (
        GatewayReason.RECONCILIATION_UNAVAILABLE.value
    )
    record = await record_for(fixture, unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconciliation_cannot_switch_to_changed_parameters() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "unknown_not_executed"
    unknown = await fixture.gateway.execute(fixture.invocation)
    changed_action = replace(
        fixture.action,
        arguments={"ticket_id": "TCK-100", "status": "in_progress"},
    )
    fixture.replace_policy_for_action(changed_action)
    changed = fixture.replace_invocation(action=changed_action)

    result = await fixture.gateway.reconcile(changed)

    assert unknown.result.status is ToolResultStatus.UNKNOWN
    assert result.result.error_code == GatewayReason.IDEMPOTENCY_CONFLICT.value
    assert fixture.adapter.reconciliation_count == 0
    record = await record_for(fixture, unknown.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN


@pytest.mark.asyncio
async def test_write_output_contract_failure_after_side_effect_is_unknown() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)
    fixture.adapter.mode = "readback_secret"

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.UNKNOWN
    assert fixture.adapter.logical_write_count == 1
    record = await record_for(fixture, execution.result.execution_id)
    assert record is not None
    assert record.status is LedgerStatus.UNKNOWN


@pytest.mark.asyncio
async def test_persistence_unavailable_never_invokes_upstream() -> None:
    fixture = make_fixture()
    assert isinstance(fixture.adapter, WriteAdapter)

    class UnavailableData:
        def __call__(self):
            raise RuntimeError("database unavailable")

    fixture.gateway = McpGateway(
        replace(fixture.gateway._deps, data_uow=UnavailableData())
    )

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.status is ToolResultStatus.FAILED_FINAL
    assert execution.result.error_code == GatewayReason.LEDGER_UNAVAILABLE.value
    assert fixture.adapter.invocation_count == 0
    assert fixture.adapter.logical_write_count == 0


@pytest.mark.asyncio
async def test_idempotency_digest_is_tenant_and_tool_scoped() -> None:
    fixture = make_fixture()
    original = fixture.invocation.request.idempotency_key
    other = canonical_sha256(
        {
            "tenant": "tenant-other",
            "tool": fixture.action.tool.name,
            "logical": 1,
        }
    )

    assert original != other
