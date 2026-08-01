from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from flowpilot_domain import Task
from flowpilot_persistence import (
    CoordinationRebuilder,
    CoordinationSignal,
    MemoryDataUnitOfWorkFactory,
    MemoryRedisClient,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
    RedisCoordinationAdapter,
)

NOW = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)


def runnable_task(
    source: Task,
    *,
    tenant_id: str,
    task_id: str,
    thread_id: str,
    run_generation: int,
) -> Task:
    value = source.to_mapping()
    value.update(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "thread_id": thread_id,
            "status": "RUNNABLE",
            "run_generation": run_generation,
            "active_run_id": None,
            "latest_checkpoint_id": None,
            "waiting_on": None,
            "result_ref": None,
            "error": None,
            "completed_at": None,
        }
    )
    value["security_context"]["tenant_id"] = tenant_id
    return Task.from_mapping(value)


def task_event(
    *,
    event_id: str,
    tenant_id: str,
    task_id: str,
    sequence: int = 1,
    available_at: datetime = NOW,
) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        aggregate_type="task",
        aggregate_id=task_id,
        sequence=sequence,
        event_type="task.status.changed.v1",
        payload={"from": "RECEIVED", "to": "RUNNABLE"},
        occurred_at=NOW,
        available_at=available_at,
    )


def test_clean_lease_release_preserves_monotonic_fencing(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        task = runnable_task(
            task_projection,
            tenant_id="tenant-a",
            task_id="task_release123",
            thread_id="thread_release123",
            run_generation=0,
        )
        factory.database.seed_task(task)
        async with factory() as data:
            first = await data.leases.acquire(
                task.tenant_id,
                task.task_id,
                "worker-a",
                now=NOW,
                ttl=timedelta(minutes=1),
            )
            await data.commit()

        async with factory() as data:
            await data.leases.release(first)
            await data.commit()

        async with factory() as data:
            with pytest.raises(PersistenceError) as stale:
                await data.leases.assert_fence(first, now=NOW)
            assert stale.value.code is PersistenceErrorCode.STALE_FENCE
            with pytest.raises(PersistenceError) as repeated_release:
                await data.leases.release(first)
            assert repeated_release.value.code is PersistenceErrorCode.LEASE_LOST

        async with factory() as data:
            second = await data.leases.acquire(
                task.tenant_id,
                task.task_id,
                "worker-b",
                now=NOW,
                ttl=timedelta(minutes=1),
            )
            assert second.run_generation == first.run_generation + 1
            await data.leases.assert_fence(second, now=NOW)

    asyncio.run(scenario())


def test_published_outbox_rebuilds_only_current_runnable_tasks(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        runnable = runnable_task(
            task_projection,
            tenant_id="tenant-a",
            task_id="task_runnable123",
            thread_id="thread_runnable123",
            run_generation=4,
        )
        terminal_value = task_projection.to_mapping()
        terminal_value.update(
            {
                "task_id": "task_terminal123",
                "thread_id": "thread_terminal123",
            }
        )
        terminal = Task.from_mapping(terminal_value)
        factory.database.seed_task(runnable)
        factory.database.seed_task(terminal)
        async with factory() as data:
            runnable_event = task_event(
                event_id="evt_runnable123",
                tenant_id="tenant-a",
                task_id=runnable.task_id,
            )
            terminal_event = task_event(
                event_id="evt_terminal123",
                tenant_id="tenant-a",
                task_id=terminal.task_id,
            )
            await data.outbox.append(runnable_event)
            await data.outbox.append(terminal_event)
            await data.outbox.mark_published(
                "tenant-a",
                runnable_event.event_id,
                published_at=NOW + timedelta(seconds=1),
            )
            await data.outbox.mark_published(
                "tenant-a",
                terminal_event.event_id,
                published_at=NOW + timedelta(seconds=1),
            )
            await data.commit()

        client = MemoryRedisClient()
        coordination = RedisCoordinationAdapter(client)
        await coordination.signal(
            CoordinationSignal(
                tenant_id="tenant-a",
                task_id="task_stale000",
                run_generation=1,
                available_at=NOW,
            )
        )
        await coordination.signal(
            CoordinationSignal(
                tenant_id="tenant-b",
                task_id="task_other123",
                run_generation=9,
                available_at=NOW,
            )
        )
        rebuilt = await CoordinationRebuilder(
            factory,
            coordination,
        ).rebuild(["tenant-a"], now=NOW + timedelta(minutes=1))

        assert rebuilt == 1
        assert set(client.values) == {
            coordination.key("tenant-a", runnable.task_id),
            coordination.key("tenant-b", "task_other123"),
        }
        payload = json.loads(
            client.values[coordination.key("tenant-a", runnable.task_id)]
        )
        assert payload["run_generation"] == runnable.run_generation
        assert terminal.task_id not in "".join(client.values.values())

    asyncio.run(scenario())


def test_latest_future_outbox_event_does_not_replay_an_older_signal(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        task = runnable_task(
            task_projection,
            tenant_id="tenant-a",
            task_id="task_delayed123",
            thread_id="thread_delayed123",
            run_generation=2,
        )
        factory.database.seed_task(task)
        async with factory() as data:
            await data.outbox.append(
                task_event(
                    event_id="evt_delayed111",
                    tenant_id="tenant-a",
                    task_id=task.task_id,
                )
            )
            await data.outbox.append(
                task_event(
                    event_id="evt_delayed222",
                    tenant_id="tenant-a",
                    task_id=task.task_id,
                    sequence=2,
                    available_at=NOW + timedelta(hours=1),
                )
            )
            await data.commit()

        client = MemoryRedisClient()
        rebuilt = await CoordinationRebuilder(
            factory,
            RedisCoordinationAdapter(client),
        ).rebuild(["tenant-a"], now=NOW)
        assert rebuilt == 0
        assert client.values == {}

    asyncio.run(scenario())


def test_rebuild_fails_before_clearing_redis_for_missing_task_fact() -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        async with factory() as data:
            await data.outbox.append(
                task_event(
                    event_id="evt_missing123",
                    tenant_id="tenant-a",
                    task_id="task_missing123",
                )
            )
            await data.commit()

        client = MemoryRedisClient()
        coordination = RedisCoordinationAdapter(client)
        await coordination.signal(
            CoordinationSignal(
                tenant_id="tenant-a",
                task_id="task_existing123",
                run_generation=1,
                available_at=NOW,
            )
        )
        before = dict(client.values)
        with pytest.raises(PersistenceError) as caught:
            await CoordinationRebuilder(factory, coordination).rebuild(
                ["tenant-a"],
                now=NOW,
            )
        assert caught.value.code is PersistenceErrorCode.DRIVER_PROTOCOL
        assert client.values == before

    asyncio.run(scenario())
