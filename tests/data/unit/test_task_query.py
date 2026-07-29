from __future__ import annotations

import asyncio

import pytest
from flowpilot_domain import Task
from flowpilot_persistence import (
    MemoryDataUnitOfWorkFactory,
    PersistenceError,
    PersistenceErrorCode,
)


def test_memory_task_query_returns_exact_projection(task_projection: Task) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        factory.database.seed_task(task_projection)

        async with factory() as unit_of_work:
            restored = await unit_of_work.tasks.get(
                task_projection.tenant_id,
                task_projection.task_id,
            )

        assert restored == task_projection

    asyncio.run(scenario())


def test_memory_task_query_returns_none_for_missing_and_other_tenant(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        factory.database.seed_task(task_projection)

        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.get(
                    task_projection.tenant_id,
                    "task_missing000",
                )
                is None
            )
            assert (
                await unit_of_work.tasks.get(
                    "tenant-b",
                    task_projection.task_id,
                )
                is None
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("requested_tenant", "requested_task"),
    [
        ("tenant-b", "task_corrupt00"),
        ("tenant-a", "task_other000"),
    ],
)
def test_memory_task_query_fails_closed_for_corrupt_identity(
    task_projection: Task,
    requested_tenant: str,
    requested_task: str,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        factory.database.state.tasks[(requested_tenant, requested_task)] = (
            task_projection
        )

        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.tasks.get(requested_tenant, requested_task)
            assert caught.value.code is PersistenceErrorCode.DRIVER_PROTOCOL

    asyncio.run(scenario())
