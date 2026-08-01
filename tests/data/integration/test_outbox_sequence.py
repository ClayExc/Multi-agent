"""FP-DATA-003: Outbox at-least-once, per-task ordering, dedup and gaps.

RUN_ID: run_g2_outbox_sequence_001

Evidence scope (tests/data/integration/test_outbox_sequence.py):
- redelivery of the same event is idempotent (at-least-once source)
- unpublished events are drained in outbox order (per-task ordering)
- sequence_gaps reports missing per-task sequences (hole detection)
- consumer_inbox.accept_once deduplicates redeliveries and rejects
  fingerprint drift (consumer dedup)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from flowpilot_persistence import (
    MemoryDataUnitOfWorkFactory,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
)

NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)


def event(
    event_id: str,
    sequence: int,
    *,
    tenant_id: str = "tenant-a",
    task_id: str = "task_12345678",
    event_type: str = "task.status.changed.v1",
    payload: dict[str, object] | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        aggregate_type="task",
        aggregate_id=task_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload or {"from": "RUNNING", "to": "COMPLETED"},
        occurred_at=NOW + timedelta(seconds=sequence),
        available_at=NOW,
    )


def test_redelivery_of_the_same_event_is_idempotent() -> None:
    """Appending the same event twice returns the same delivery (at-least-once)."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        first = event("evt_12345678", 1)
        async with factory() as unit_of_work:
            delivered = await unit_of_work.outbox.append(first)
            replayed = await unit_of_work.outbox.append(first)
            assert replayed.event == first
            assert delivered.event == first
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            unpublished = await unit_of_work.outbox.unpublished(
                "tenant-a", now=NOW + timedelta(seconds=60), limit=10
            )
            assert [item.event.event_id for item in unpublished] == [
                "evt_12345678"
            ]

    asyncio.run(scenario())


def test_event_id_is_bound_to_one_fingerprint() -> None:
    """Reusing an event_id for different content is a conflict."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(event("evt_12345678", 1))
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.outbox.append(
                    event(
                        "evt_12345678",
                        1,
                        payload={"from": "RECEIVED", "to": "RUNNING"},
                    )
                )
            assert caught.value.code is PersistenceErrorCode.CONFLICT

    asyncio.run(scenario())


def test_sequence_is_occupied_by_one_event() -> None:
    """Two different events cannot share a per-task sequence."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(event("evt_12345678", 1))
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.outbox.append(event("evt_87654321", 1))
            assert (
                caught.value.code is PersistenceErrorCode.VERSION_CONFLICT
            )

    asyncio.run(scenario())


def test_unpublished_events_drain_in_outbox_order() -> None:
    """Unpublished delivery is ordered by available_at then per-task sequence."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(
                event("evt_00000002", 2, payload={"from": "A", "to": "B"})
            )
            await unit_of_work.outbox.append(
                event("evt_00000001", 1, payload={"from": "A", "to": "B"})
            )
            await unit_of_work.outbox.append(
                event(
                    "evt_00000003",
                    3,
                    task_id="task_87654321",
                    payload={"from": "A", "to": "B"},
                )
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            unpublished = await unit_of_work.outbox.unpublished(
                "tenant-a", now=NOW + timedelta(seconds=60), limit=10
            )
            assert [
                (item.event.aggregate_id, item.event.sequence)
                for item in unpublished
            ] == [
                ("task_12345678", 1),
                ("task_12345678", 2),
                ("task_87654321", 3),
            ]

    asyncio.run(scenario())


def test_sequence_gaps_report_missing_per_task_sequences() -> None:
    """sequence_gaps reports holes; absent aggregates have no gaps."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(event("evt_00000001", 1))
            await unit_of_work.outbox.append(event("evt_00000003", 3))
            await unit_of_work.outbox.append(event("evt_00000005", 5))
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            assert (
                await unit_of_work.outbox.sequence_gaps(
                    "tenant-a", "task", "task_12345678"
                )
            ) == (2, 4)
            assert (
                await unit_of_work.outbox.sequence_gaps(
                    "tenant-a", "task", "task_87654321"
                )
            ) == ()
            assert (
                await unit_of_work.outbox.sequence_gaps(
                    "tenant-b", "task", "task_12345678"
                )
            ) == ()

    asyncio.run(scenario())


def test_consumer_inbox_deduplicates_redeliveries() -> None:
    """accept_once returns True once; identical redelivery is a duplicate."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        digest = "sha256:" + "d" * 64
        async with factory() as unit_of_work:
            accepted = await unit_of_work.consumer_inbox.accept_once(
                "tenant-a",
                "worker-events",
                "evt_12345678",
                digest,
                processed_at=NOW,
            )
            duplicate = await unit_of_work.consumer_inbox.accept_once(
                "tenant-a",
                "worker-events",
                "evt_12345678",
                digest,
                processed_at=NOW,
            )
            assert accepted is True
            assert duplicate is False
            await unit_of_work.commit()

        # The dedup record is durable across transactions.
        async with factory() as unit_of_work:
            replayed = await unit_of_work.consumer_inbox.accept_once(
                "tenant-a",
                "worker-events",
                "evt_12345678",
                digest,
                processed_at=NOW + timedelta(seconds=10),
            )
            assert replayed is False

    asyncio.run(scenario())


def test_consumer_inbox_rejects_fingerprint_drift() -> None:
    """A redelivery with a different payload hash is an idempotency conflict."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.consumer_inbox.accept_once(
                "tenant-a",
                "worker-events",
                "evt_12345678",
                "sha256:" + "d" * 64,
                processed_at=NOW,
            )
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.consumer_inbox.accept_once(
                    "tenant-a",
                    "worker-events",
                    "evt_12345678",
                    "sha256:" + "e" * 64,
                    processed_at=NOW,
                )
            assert (
                caught.value.code
                is PersistenceErrorCode.IDEMPOTENCY_CONFLICT
            )

    asyncio.run(scenario())


def test_outbox_payload_rejects_secret_material() -> None:
    """Outbox payloads cannot carry plaintext secret keys (FP-SEC-006)."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.outbox.append(
                    event(
                        "evt_12345678",
                        1,
                        payload={
                            "from": "RUNNING",
                            "to": "COMPLETED",
                            "api_key": "sk-plaintext",
                        },
                    )
                )
            assert caught.value.code is PersistenceErrorCode.SECRET_MATERIAL

    asyncio.run(scenario())


def test_publish_mark_and_gap_roundtrip() -> None:
    """Marked events leave the unpublished pool; gaps survive marking."""

    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as unit_of_work:
            await unit_of_work.outbox.append(event("evt_00000001", 1))
            await unit_of_work.outbox.append(event("evt_00000003", 3))
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            await unit_of_work.outbox.mark_published(
                "tenant-a",
                "evt_00000001",
                published_at=NOW + timedelta(seconds=30),
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            unpublished = await unit_of_work.outbox.unpublished(
                "tenant-a", now=NOW + timedelta(seconds=60), limit=10
            )
            assert [item.event.event_id for item in unpublished] == [
                "evt_00000003"
            ]
            assert (
                await unit_of_work.outbox.sequence_gaps(
                    "tenant-a", "task", "task_12345678"
                )
            ) == (2,)

    asyncio.run(scenario())
