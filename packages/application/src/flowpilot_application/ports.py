from __future__ import annotations

from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from flowpilot_domain import Task, TaskCommand

from .models import (
    ExecutionReceipt,
    RequestReferenceQuery,
    ResolvedRequestReference,
    ResultArtifactDraft,
    ResultArtifactReceipt,
    StoredCommand,
)


class VersionSlotReservation(StrEnum):
    RESERVED = "reserved"
    CONFLICT = "conflict"


class ExecutionPort(Protocol):
    """Idempotent command submission boundary implemented by S2-RUNTIME."""

    async def submit(self, command: TaskCommand) -> ExecutionReceipt:
        """Submit once by command_id, returning DUPLICATE for a safe replay."""


class RequestReferenceResolverPort(Protocol):
    """Resolve an opaque message reference into a trusted, redacted observation."""

    async def resolve(
        self, query: RequestReferenceQuery
    ) -> ResolvedRequestReference | None:
        """Return None for an unknown tenant-scoped reference."""


class ResultArtifactPort(Protocol):
    """Atomically save result content and return only its opaque reference."""

    async def put(self, draft: ResultArtifactDraft) -> ResultArtifactReceipt:
        """Deduplicate by tenant/idempotency key and fail on digest conflicts."""


class TaskRepositoryPort(Protocol):
    """Read-only task facts needed by command intake."""

    async def get_version(self, tenant_id: str, task_id: str) -> int | None:
        """Return the tenant-scoped task version, or None when absent."""


class TaskQueryPort(Protocol):
    """Tenant-scoped read boundary for the external Task projection."""

    async def get(self, tenant_id: str, task_id: str) -> Task | None:
        """Return the exact tenant/task projection, or None when absent."""


class TaskQueryUnitOfWork(Protocol):
    """Read transaction boundary for a tenant-scoped Task projection."""

    @property
    def tasks(self) -> TaskQueryPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class TaskQueryUnitOfWorkFactory(Protocol):
    def __call__(self) -> TaskQueryUnitOfWork: ...


class CommandInboxPort(Protocol):
    """Transactional command deduplication and version-slot boundary."""

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> StoredCommand | None: ...

    async def get_by_command_id(
        self, tenant_id: str, command_id: str
    ) -> StoredCommand | None: ...

    async def reserve_version_slot(
        self,
        tenant_id: str,
        task_id: str,
        expected_task_version: int | None,
        command_id: str,
    ) -> VersionSlotReservation: ...

    async def add(self, stored: StoredCommand) -> None: ...

    async def record_execution(
        self, tenant_id: str, command_id: str, receipt: ExecutionReceipt
    ) -> StoredCommand: ...


class UnitOfWork(Protocol):
    tasks: TaskRepositoryPort
    commands: CommandInboxPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
