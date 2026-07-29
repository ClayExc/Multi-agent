from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Self

from flowpilot_domain import TaskCommand

from .models import ExecutionDisposition, ExecutionReceipt, StoredCommand
from .ports import VersionSlotReservation


@dataclass(slots=True)
class InMemoryStore:
    task_versions: dict[tuple[str, str], int] = field(default_factory=dict)
    commands_by_id: dict[tuple[str, str], StoredCommand] = field(
        default_factory=dict
    )
    command_id_by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    version_slots: dict[tuple[str, str, int | None], str] = field(
        default_factory=dict
    )


class FakeTaskRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get_version(self, tenant_id: str, task_id: str) -> int | None:
        return self._store.task_versions.get((tenant_id, task_id))


class FakeCommandInbox:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> StoredCommand | None:
        command_id = self._store.command_id_by_key.get(
            (tenant_id, idempotency_key)
        )
        if command_id is None:
            return None
        return self._store.commands_by_id[(tenant_id, command_id)]

    async def get_by_command_id(
        self, tenant_id: str, command_id: str
    ) -> StoredCommand | None:
        return self._store.commands_by_id.get((tenant_id, command_id))

    async def reserve_version_slot(
        self,
        tenant_id: str,
        task_id: str,
        expected_task_version: int | None,
        command_id: str,
    ) -> VersionSlotReservation:
        slot = (tenant_id, task_id, expected_task_version)
        owner = self._store.version_slots.get(slot)
        if owner is not None and owner != command_id:
            return VersionSlotReservation.CONFLICT
        self._store.version_slots[slot] = command_id
        return VersionSlotReservation.RESERVED

    async def add(self, stored: StoredCommand) -> None:
        command = stored.command
        self._store.commands_by_id[(command.tenant_id, command.command_id)] = stored
        self._store.command_id_by_key[
            (command.tenant_id, command.idempotency_key)
        ] = command.command_id

    async def record_execution(
        self, tenant_id: str, command_id: str, receipt: ExecutionReceipt
    ) -> StoredCommand:
        key = (tenant_id, command_id)
        existing = self._store.commands_by_id[key]
        updated = replace(existing, execution_receipt=receipt)
        self._store.commands_by_id[key] = updated
        return updated


class FakeUnitOfWork:
    def __init__(self, shared: InMemoryStore) -> None:
        self._shared = shared
        self._working: InMemoryStore | None = None
        self.tasks: FakeTaskRepository
        self.commands: FakeCommandInbox
        self._committed = False

    async def __aenter__(self) -> Self:
        self._working = InMemoryStore(
            task_versions=dict(self._shared.task_versions),
            commands_by_id=dict(self._shared.commands_by_id),
            command_id_by_key=dict(self._shared.command_id_by_key),
            version_slots=dict(self._shared.version_slots),
        )
        self.tasks = FakeTaskRepository(self._working)
        self.commands = FakeCommandInbox(self._working)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None and self._committed and self._working is not None:
            self._shared.task_versions = self._working.task_versions
            self._shared.commands_by_id = self._working.commands_by_id
            self._shared.command_id_by_key = self._working.command_id_by_key
            self._shared.version_slots = self._working.version_slots
        self._working = None

    async def commit(self) -> None:
        self._committed = True


class FakeUnitOfWorkFactory:
    def __init__(self, store: InMemoryStore | None = None) -> None:
        self.store = store or InMemoryStore()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.store)


class FakeExecutionPort:
    def __init__(self) -> None:
        self.receipts: dict[tuple[str, str], ExecutionReceipt] = {}
        self.calls: list[TaskCommand] = []
        self.failure: Exception | None = None
        self.invalid_receipt = False

    async def submit(self, command: TaskCommand) -> ExecutionReceipt:
        self.calls.append(command)
        if self.failure is not None:
            raise self.failure
        key = (command.tenant_id, command.command_id)
        existing = self.receipts.get(key)
        if existing is not None:
            return replace(existing, disposition=ExecutionDisposition.DUPLICATE)
        receipt = ExecutionReceipt(
            command_id=(
                "cmd_invalid000" if self.invalid_receipt else command.command_id
            ),
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            disposition=ExecutionDisposition.ACCEPTED,
            execution_ref=f"execution:{command.command_id}",
        )
        self.receipts[key] = receipt
        return receipt
