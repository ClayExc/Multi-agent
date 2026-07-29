from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from flowpilot_persistence import (
    ExecutionIntent,
    MemoryDataUnitOfWorkFactory,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
)

NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)


def event(event_id: str, sequence: int, *, payload_value: int = 1) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        tenant_id="tenant-a",
        aggregate_type="task",
        aggregate_id="task_12345678",
        sequence=sequence,
        event_type="task.status.changed.v1",
        payload={"value": payload_value},
        occurred_at=NOW + timedelta(seconds=sequence),
        available_at=NOW,
    )


def test_ledger_and_outbox_roll_back_together(
    execution_intent: ExecutionIntent,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        with pytest.raises(RuntimeError, match="fault injection"):
            async with factory() as unit_of_work:
                await unit_of_work.ledger.prepare(execution_intent)
                await unit_of_work.outbox.append(event("evt_12345678", 1))
                raise RuntimeError("fault injection")

        async with factory() as unit_of_work:
            assert (
                await unit_of_work.ledger.get(
                    execution_intent.tenant_id,
                    execution_intent.tool_execution_id,
                )
                is None
            )
            assert (
                await unit_of_work.outbox.unpublished(
                    "tenant-a", now=NOW, limit=10
                )
                == ()
            )

    asyncio.run(scenario())


def test_outbox_redelivery_and_sequence_gap_are_explicit() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        first = event("evt_12345678", 1)
        third = event("evt_87654321", 3)
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(first)
            replay = await unit_of_work.outbox.append(first)
            assert replay.event == first
            await unit_of_work.outbox.append(third)
            assert (
                await unit_of_work.outbox.sequence_gaps(
                    "tenant-a", "task", "task_12345678"
                )
                == (2,)
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            unpublished = await unit_of_work.outbox.unpublished(
                "tenant-a", now=NOW + timedelta(seconds=10), limit=10
            )
            assert [item.event.sequence for item in unpublished] == [1, 3]
            await unit_of_work.outbox.mark_published(
                "tenant-a",
                first.event_id,
                published_at=NOW + timedelta(seconds=20),
            )
            accepted = await unit_of_work.consumer_inbox.accept_once(
                "tenant-a",
                "worker-events",
                first.event_id,
                "sha256:" + "d" * 64,
                processed_at=NOW,
            )
            duplicate = await unit_of_work.consumer_inbox.accept_once(
                "tenant-a",
                "worker-events",
                first.event_id,
                "sha256:" + "d" * 64,
                processed_at=NOW,
            )
            assert accepted is True
            assert duplicate is False
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.consumer_inbox.accept_once(
                    "tenant-a",
                    "worker-events",
                    first.event_id,
                    "sha256:" + "e" * 64,
                    processed_at=NOW,
                )
            assert (
                caught.value.code
                is PersistenceErrorCode.IDEMPOTENCY_CONFLICT
            )

    asyncio.run(scenario())


def test_outbox_sequence_collision_does_not_overwrite() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(event("evt_12345678", 1))
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.outbox.append(event("evt_99999999", 1))
            assert caught.value.code is PersistenceErrorCode.VERSION_CONFLICT

    asyncio.run(scenario())
