from __future__ import annotations

import asyncio
from collections.abc import Callable

from flowpilot_application import (
    CommandIntakeService,
    StoredCommand,
)
from flowpilot_application.testing import FakeExecutionPort
from flowpilot_domain import TaskCommand
from flowpilot_persistence import MemoryDataUnitOfWorkFactory


def test_command_intake_commits_and_replays(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        unit_of_work = MemoryDataUnitOfWorkFactory()
        execution = FakeExecutionPort()
        service = CommandIntakeService(
            unit_of_work=unit_of_work,
            execution=execution,
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
