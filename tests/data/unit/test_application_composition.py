from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from flowpilot_application import compose_core_application
from flowpilot_application.testing import FakeExecutionPort
from flowpilot_domain import Task, TaskCommand
from flowpilot_persistence import (
    MemoryDataUnitOfWorkFactory,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
    compose_application_unit_of_work_factories,
)

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def _event(task: Task, *, event_id: str = "evt_12345678") -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        tenant_id=task.tenant_id,
        aggregate_type="task",
        aggregate_id=task.task_id,
        sequence=1,
        event_type="task.completed.v1",
        payload={"outcome": "knowledge_answered", "citation_count": 1},
        occurred_at=NOW,
        available_at=NOW,
    )


def test_composed_command_and_query_factories_use_fresh_transactions(
    task_projection: Task,
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        data = MemoryDataUnitOfWorkFactory()
        data.database.seed_task(task_projection)
        composed = compose_application_unit_of_work_factories(data)
        command = command_factory(
            tenant_id=task_projection.tenant_id,
            task_id="task_compose123",
        )
        execution = FakeExecutionPort()
        services = compose_core_application(
            command_unit_of_work=composed.command_unit_of_work,
            task_query_unit_of_work=composed.task_query_unit_of_work,
            execution=execution,
            clock=lambda: NOW,
        )

        accepted = await services.command_intake.accept(command)
        assert accepted.replayed is False
        assert len(execution.calls) == 1

        assert (
            await services.task_query.get(
                task_projection.tenant_id,
                task_projection.task_id,
            )
            == task_projection
        )

        async with composed.command_unit_of_work() as replay_uow:
            stored = await replay_uow.commands.get_by_command_id(
                command.tenant_id,
                command.command_id,
            )
            assert stored is not None
            assert stored.command == command
            assert stored.execution_receipt == accepted.execution_receipt

    asyncio.run(scenario())


def test_composed_event_uow_projects_and_commits_outbox_with_inbox(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        data = MemoryDataUnitOfWorkFactory()
        data.database.seed_task(task_projection)
        event = _event(task_projection)
        async with data() as seed_uow:
            await seed_uow.outbox.append(event)
            await seed_uow.commit()

        composed = compose_application_unit_of_work_factories(data)
        async with composed.task_event_unit_of_work() as event_uow:
            assert (
                await event_uow.tasks.get(event.tenant_id, event.aggregate_id)
                == task_projection
            )
            views = await event_uow.outbox.unpublished(
                event.tenant_id,
                now=NOW,
                limit=10,
            )
            assert len(views) == 1
            assert views[0].event_id == event.event_id
            assert views[0].payload == event.payload
            assert await event_uow.consumer_inbox.accept_once(
                event.tenant_id,
                "stream:tenant-a",
                event.event_id,
                "sha256:" + "a" * 64,
                processed_at=NOW,
            )
            marked = await event_uow.outbox.mark_published(
                event.tenant_id,
                event.event_id,
                published_at=NOW,
            )
            assert marked.event_id == event.event_id
            await event_uow.commit()

        async with composed.task_event_unit_of_work() as replay_uow:
            assert (
                await replay_uow.outbox.unpublished(
                    event.tenant_id,
                    now=NOW,
                    limit=10,
                )
                == ()
            )
            assert not await replay_uow.consumer_inbox.accept_once(
                event.tenant_id,
                "stream:tenant-a",
                event.event_id,
                "sha256:" + "a" * 64,
                processed_at=NOW,
            )

    asyncio.run(scenario())


def test_composed_event_uow_rolls_back_publish_and_consumer_acceptance(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        data = MemoryDataUnitOfWorkFactory()
        data.database.seed_task(task_projection)
        event = _event(task_projection)
        async with data() as seed_uow:
            await seed_uow.outbox.append(event)
            await seed_uow.commit()

        composed = compose_application_unit_of_work_factories(data)
        async with composed.task_event_unit_of_work() as interrupted_uow:
            assert await interrupted_uow.consumer_inbox.accept_once(
                event.tenant_id,
                "stream:tenant-a",
                event.event_id,
                "sha256:" + "b" * 64,
                processed_at=NOW,
            )
            await interrupted_uow.outbox.mark_published(
                event.tenant_id,
                event.event_id,
                published_at=NOW,
            )

        async with composed.task_event_unit_of_work() as retry_uow:
            assert len(
                await retry_uow.outbox.unpublished(
                    event.tenant_id,
                    now=NOW,
                    limit=10,
                )
            ) == 1
            assert await retry_uow.consumer_inbox.accept_once(
                event.tenant_id,
                "stream:tenant-a",
                event.event_id,
                "sha256:" + "b" * 64,
                processed_at=NOW,
            )

    asyncio.run(scenario())


def test_composed_uows_fail_closed_on_missing_or_switched_tenant(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        data = MemoryDataUnitOfWorkFactory()
        data.database.seed_task(task_projection)
        composed = compose_application_unit_of_work_factories(data)

        async with composed.task_event_unit_of_work() as event_uow:
            with pytest.raises(PersistenceError) as missing:
                await event_uow.tasks.get("", task_projection.task_id)
            assert missing.value.code is PersistenceErrorCode.TENANT_REQUIRED

        async with composed.task_event_unit_of_work() as event_uow:
            assert (
                await event_uow.tasks.get(
                    task_projection.tenant_id,
                    task_projection.task_id,
                )
                == task_projection
            )
            with pytest.raises(PersistenceError) as switched:
                await event_uow.outbox.unpublished(
                    "tenant-b",
                    now=NOW,
                    limit=10,
                )
            assert switched.value.code is PersistenceErrorCode.TENANT_MISMATCH

        async with composed.task_query_unit_of_work() as query_uow:
            assert await query_uow.tasks.get(
                "tenant-b",
                task_projection.task_id,
            ) is None

    asyncio.run(scenario())
