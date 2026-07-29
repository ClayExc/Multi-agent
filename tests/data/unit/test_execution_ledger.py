from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from flowpilot_persistence import (
    ExecutionIntent,
    ExecutionOutcome,
    LedgerStatus,
    MemoryDataUnitOfWorkFactory,
    PersistenceError,
    PersistenceErrorCode,
    RetryBasis,
)


def test_prepare_is_idempotent_and_binding_is_immutable(
    execution_intent: ExecutionIntent,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            first = await unit_of_work.ledger.prepare(execution_intent)
            replay = await unit_of_work.ledger.prepare(execution_intent)
            assert replay == first
            await unit_of_work.commit()

        conflicting = replace(
            execution_intent,
            tool_execution_id="tex_87654321",
            request_id="treq_87654321",
        )
        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.ledger.prepare(conflicting)
            assert caught.value.code is PersistenceErrorCode.IDEMPOTENCY_CONFLICT

    asyncio.run(scenario())


def test_approval_expiry_mismatch_is_rejected_before_storage(
    execution_intent: ExecutionIntent,
) -> None:
    approval = copy.deepcopy(dict(execution_intent.approval or {}))
    approval["expires_at"] = "2026-07-28T09:01:00Z"
    with pytest.raises(PersistenceError, match="approval"):
        replace(
            execution_intent,
            approval=approval,
            approval_expires_at=(
                execution_intent.planned_action_expires_at
                + timedelta(minutes=1)
            ),
        )


def test_policy_expiry_mismatch_is_rejected_before_storage(
    execution_intent: ExecutionIntent,
) -> None:
    policy_value = execution_intent.binding_mapping()["policy_decision"]
    assert isinstance(policy_value, dict)
    policy = copy.deepcopy(policy_value)
    policy["expires_at"] = "2026-07-28T09:01:00Z"
    with pytest.raises(PersistenceError, match="policy"):
        replace(execution_intent, policy_decision=policy)


def test_policy_required_approval_cannot_be_omitted(
    execution_intent: ExecutionIntent,
) -> None:
    with pytest.raises(PersistenceError, match="requires"):
        replace(
            execution_intent,
            approval_id=None,
            approval=None,
            approval_expires_at=None,
        )


def test_unknown_requires_reconciliation_before_retry(
    execution_intent: ExecutionIntent,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.ledger.prepare(execution_intent)
            await unit_of_work.ledger.mark_running(
                execution_intent.tenant_id,
                execution_intent.tool_execution_id,
                now=execution_intent.created_at,
            )
            unknown = ExecutionOutcome(
                status=LedgerStatus.UNKNOWN,
                recorded_at=execution_intent.created_at + timedelta(seconds=5),
                retryable=False,
                error_code="UPSTREAM_RESULT_UNKNOWN",
                reconciliation={
                    "method": "business_key_lookup",
                    "status": "pending",
                },
            )
            await unit_of_work.ledger.record_outcome(
                execution_intent.tenant_id,
                execution_intent.tool_execution_id,
                unknown,
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.ledger.mark_running(
                    execution_intent.tenant_id,
                    execution_intent.tool_execution_id,
                    now=execution_intent.created_at + timedelta(seconds=10),
                )
            assert (
                caught.value.code
                is PersistenceErrorCode.RECONCILIATION_REQUIRED
            )
            pending = await unit_of_work.ledger.pending_reconciliation(
                execution_intent.tenant_id, limit=10
            )
            assert [record.intent.tool_execution_id for record in pending] == [
                execution_intent.tool_execution_id
            ]

            confirmed = ExecutionOutcome(
                status=LedgerStatus.FAILED_RETRYABLE,
                recorded_at=execution_intent.created_at + timedelta(seconds=20),
                retryable=True,
                retry_basis=RetryBasis.CONFIRMED_NOT_EXECUTED,
                error_code="UPSTREAM_CONFIRMED_NOT_EXECUTED",
                verification={
                    "method": "business_key_lookup",
                    "matched": False,
                    "observed_ref": "evidence://lookup/12345678",
                },
            )
            await unit_of_work.ledger.record_outcome(
                execution_intent.tenant_id,
                execution_intent.tool_execution_id,
                confirmed,
            )
            running = await unit_of_work.ledger.mark_running(
                execution_intent.tenant_id,
                execution_intent.tool_execution_id,
                now=execution_intent.created_at + timedelta(seconds=21),
            )
            assert running.status is LedgerStatus.RUNNING
            assert running.attempt_count == 2

    asyncio.run(scenario())


def test_unknown_cannot_use_not_sent_as_reconciliation_proof(
    execution_intent: ExecutionIntent,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.ledger.prepare(execution_intent)
            await unit_of_work.ledger.mark_running(
                execution_intent.tenant_id,
                execution_intent.tool_execution_id,
                now=execution_intent.created_at,
            )
            await unit_of_work.ledger.record_outcome(
                execution_intent.tenant_id,
                execution_intent.tool_execution_id,
                ExecutionOutcome(
                    status=LedgerStatus.UNKNOWN,
                    recorded_at=execution_intent.created_at
                    + timedelta(seconds=1),
                    retryable=False,
                    error_code="UPSTREAM_RESULT_UNKNOWN",
                    reconciliation={"status": "pending"},
                ),
            )
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.ledger.record_outcome(
                    execution_intent.tenant_id,
                    execution_intent.tool_execution_id,
                    ExecutionOutcome(
                        status=LedgerStatus.FAILED_RETRYABLE,
                        recorded_at=execution_intent.created_at
                        + timedelta(seconds=2),
                        retryable=True,
                        retry_basis=RetryBasis.NOT_SENT,
                        error_code="NETWORK_NOT_SENT",
                    ),
                )
            assert (
                caught.value.code
                is PersistenceErrorCode.RECONCILIATION_REQUIRED
            )

    asyncio.run(scenario())


def test_verified_requires_authoritative_readback() -> None:
    with pytest.raises(PersistenceError) as caught:
        ExecutionOutcome(
            status=LedgerStatus.VERIFIED,
            recorded_at=datetime.now(UTC),
            retryable=False,
            data={"ticket_id": "INC-123"},
            evidence_ref=None,
            verification={"matched": True, "observed_ref": "obs://ticket/123"},
        )
    assert caught.value.code is PersistenceErrorCode.INVALID_TRANSITION
