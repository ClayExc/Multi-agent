from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace

from flowpilot_application import (
    CommandIntakeService,
    StoredCommand,
    TaskInitializationDisposition,
    VersionSlotReservation,
)
from flowpilot_application.testing import (
    FAKE_TASK_INITIALIZATION,
    FakeExecutionPort,
    FakeThreadIdFactory,
)
from flowpilot_domain import Task, TaskCommand, TaskStatus
from flowpilot_persistence import (
    MemoryDataUnitOfWorkFactory,
    PersistenceError,
)


def test_command_intake_commits_and_replays(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        unit_of_work = MemoryDataUnitOfWorkFactory()
        execution = FakeExecutionPort()
        service = CommandIntakeService(
            unit_of_work=unit_of_work,
            execution=execution,
            task_initialization=FAKE_TASK_INITIALIZATION,
            thread_id_factory=FakeThreadIdFactory(),
        )
        command = command_factory()

        first = await service.accept(command)
        replays = [await service.accept(command) for _ in range(9)]

        assert first.replayed is False
        assert all(replay.replayed for replay in replays)
        assert all(
            replay.execution_receipt == first.execution_receipt
            for replay in replays
        )
        assert len(execution.calls) == 1

    asyncio.run(scenario())


def _initial_task(task: Task, *, task_id: str, thread_id: str) -> Task:
    return replace(
        task,
        task_id=task_id,
        thread_id=thread_id,
        status=TaskStatus.RECEIVED,
        version=0,
        run_generation=0,
        waiting_on=None,
        result_ref=None,
        error=None,
        completed_at=None,
        active_run_id=None,
        latest_checkpoint_id=None,
        domain=None,
        intent=None,
        risk_level=None,
        updated_at=task.created_at,
    )


def test_memory_initialize_is_insert_only_and_tenant_bound(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        task = _initial_task(
            task_projection,
            task_id="task_initialize1",
            thread_id="thread_initialize1",
        )
        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.initialize(task.tenant_id, task)
                is TaskInitializationDisposition.INITIALIZED
            )
            assert (
                await unit_of_work.tasks.initialize(task.tenant_id, task)
                is TaskInitializationDisposition.CONFLICT
            )
            assert (
                await unit_of_work.tasks.initialize("tenant-b", task)
                is TaskInitializationDisposition.CONFLICT
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            assert await unit_of_work.tasks.get(task.tenant_id, task.task_id) == task
            assert await unit_of_work.tasks.get("tenant-b", task.task_id) is None

    asyncio.run(scenario())


def test_memory_command_failure_rolls_back_task_command_and_create_slot(
    task_projection: Task,
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        task = _initial_task(
            task_projection,
            task_id="task_rollback1",
            thread_id="thread_rollback1",
        )
        command = command_factory(task_id=task.task_id)

        try:
            async with factory() as unit_of_work:
                assert (
                    await unit_of_work.commands.reserve_version_slot(
                        command.tenant_id,
                        command.task_id,
                        -1,
                        command.command_id,
                    )
                    is VersionSlotReservation.RESERVED
                )
                assert (
                    await unit_of_work.tasks.initialize(task.tenant_id, task)
                    is TaskInitializationDisposition.INITIALIZED
                )
                stored = StoredCommand(
                    command=command,
                    accepted_at=command.issued_at,
                )
                await unit_of_work.commands.add(stored)
                await unit_of_work.commands.add(stored)
        except PersistenceError:
            pass
        else:
            raise AssertionError("duplicate Command write did not fail")

        async with factory() as unit_of_work:
            assert await unit_of_work.tasks.get(task.tenant_id, task.task_id) is None
            assert (
                await unit_of_work.commands.get_by_command_id(
                    command.tenant_id,
                    command.command_id,
                )
                is None
            )
            assert (
                await unit_of_work.commands.reserve_version_slot(
                    command.tenant_id,
                    command.task_id,
                    -1,
                    "cmd_afterrollback",
                )
                is VersionSlotReservation.RESERVED
            )

    asyncio.run(scenario())


def test_memory_task_initialization_failure_rolls_back_create_slot(
    task_projection: Task,
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        task = _initial_task(
            task_projection,
            task_id="task_rollback2",
            thread_id="thread_rollback2",
        )
        command = command_factory(task_id=task.task_id)

        async with factory() as unit_of_work:
            await unit_of_work.commands.reserve_version_slot(
                command.tenant_id,
                command.task_id,
                -1,
                command.command_id,
            )
            assert (
                await unit_of_work.tasks.initialize("tenant-b", task)
                is TaskInitializationDisposition.CONFLICT
            )

        async with factory() as unit_of_work:
            assert await unit_of_work.tasks.get(task.tenant_id, task.task_id) is None
            assert (
                await unit_of_work.commands.reserve_version_slot(
                    command.tenant_id,
                    command.task_id,
                    -1,
                    "cmd_afterfailure",
                )
                is VersionSlotReservation.RESERVED
            )

    asyncio.run(scenario())


def test_uncommitted_command_and_version_slot_roll_back(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        command = command_factory()

        async with factory() as unit_of_work:
            await unit_of_work.commands.reserve_version_slot(
                command.tenant_id,
                command.task_id,
                command.expected_task_version,
                command.command_id,
            )
            await unit_of_work.commands.add(
                StoredCommand(command=command, accepted_at=command.issued_at)
            )

        async with factory() as unit_of_work:
            assert (
                await unit_of_work.commands.get_by_command_id(
                    command.tenant_id, command.command_id
                )
                is None
            )
            reservation = await unit_of_work.commands.reserve_version_slot(
                command.tenant_id,
                command.task_id,
                command.expected_task_version,
                "cmd_rollback2",
            )
            assert reservation.value == "reserved"

    asyncio.run(scenario())


def test_task_and_command_reads_are_tenant_scoped(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        factory = MemoryDataUnitOfWorkFactory()
        factory.database.seed_task_version("tenant-a", "task_12345678", 3)
        command = command_factory()
        async with factory() as unit_of_work:
            await unit_of_work.commands.reserve_version_slot(
                command.tenant_id,
                command.task_id,
                command.expected_task_version,
                command.command_id,
            )
            await unit_of_work.commands.add(
                StoredCommand(command=command, accepted_at=command.issued_at)
            )
            await unit_of_work.commit()

        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.get_version(
                    "tenant-a", "task_12345678"
                )
                == 3
            )
            assert (
                await unit_of_work.tasks.get_version(
                    "tenant-b", "task_12345678"
                )
                is None
            )
            assert (
                await unit_of_work.commands.get_by_command_id(
                    "tenant-b", command.command_id
                )
                is None
            )

    asyncio.run(scenario())
