from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from flowpilot_domain import Task, TaskCommand

from .models import (
    ExecutionReceipt,
    OutboxEventView,
    RequestReferenceQuery,
    ResolvedRequestReference,
    ResultArtifactDraft,
    ResultArtifactReceipt,
    StoredCommand,
    TaskEventEnvelope,
)


class VersionSlotReservation(StrEnum):
    RESERVED = "reserved"
    CONFLICT = "conflict"


class TaskInitializationDisposition(StrEnum):
    INITIALIZED = "initialized"
    CONFLICT = "conflict"


class ThreadIdFactory(Protocol):
    """Generate an opaque server-owned thread identifier."""

    def __call__(self) -> str: ...


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
    """Tenant-bound Task facts and CREATE initialization in Command Tx-A."""

    async def get_version(self, tenant_id: str, task_id: str) -> int | None:
        """Return the tenant-scoped task version, or None when absent."""

    async def initialize(
        self, tenant_id: str, task: Task
    ) -> TaskInitializationDisposition:
        """Insert Task v0 once without overwriting an existing projection."""


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


class TaskEventOutboxPort(Protocol):
    """Outbox read/drain boundary consumed by the SSE subscription use case."""

    async def unpublished(
        self, tenant_id: str, *, now: datetime, limit: int
    ) -> Sequence[OutboxEventView]: ...

    async def mark_published(
        self, tenant_id: str, event_id: str, *, published_at: datetime
    ) -> OutboxEventView: ...

    async def sequence_gaps(
        self, tenant_id: str, aggregate_type: str, aggregate_id: str
    ) -> Sequence[int]: ...


class TaskEventConsumerInboxPort(Protocol):
    """Durable consumer deduplication boundary for outbox redeliveries."""

    async def accept_once(
        self,
        tenant_id: str,
        consumer_id: str,
        event_id: str,
        payload_hash: str,
        *,
        processed_at: datetime,
    ) -> bool:
        """Return True once and False for an identical redelivery."""


class TaskEventUnitOfWork(Protocol):
    """Transaction boundary for the tenant-scoped event subscription poll."""

    @property
    def tasks(self) -> TaskQueryPort: ...

    @property
    def outbox(self) -> TaskEventOutboxPort: ...

    @property
    def consumer_inbox(self) -> TaskEventConsumerInboxPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class TaskEventUnitOfWorkFactory(Protocol):
    def __call__(self) -> TaskEventUnitOfWork: ...


class EventStreamPort(Protocol):
    """Outbound task-event delivery boundary implemented by the SSE transport."""

    async def emit(self, tenant_id: str, event: TaskEventEnvelope) -> None: ...
