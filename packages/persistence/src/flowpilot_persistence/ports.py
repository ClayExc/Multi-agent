from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from types import TracebackType
from typing import Protocol, Self

from flowpilot_application import (
    CommandInboxPort,
    TaskRepositoryPort,
    UnitOfWork,
)

from .models import (
    CheckpointRecord,
    CoordinationSignal,
    ExecutionIntent,
    ExecutionOutcome,
    ExecutionRecord,
    LeaseFence,
    OutboxDelivery,
    OutboxEvent,
)

PERSISTENCE_PORT_VERSION = "flowpilot.persistence-ports.m0.v2"


class ExecutionLedgerPort(Protocol):
    async def prepare(self, intent: ExecutionIntent) -> ExecutionRecord: ...

    async def get(
        self, tenant_id: str, tool_execution_id: str
    ) -> ExecutionRecord | None: ...

    async def mark_running(
        self,
        tenant_id: str,
        tool_execution_id: str,
        *,
        now: datetime,
    ) -> ExecutionRecord: ...

    async def record_outcome(
        self,
        tenant_id: str,
        tool_execution_id: str,
        outcome: ExecutionOutcome,
    ) -> ExecutionRecord: ...

    async def pending_reconciliation(
        self, tenant_id: str, *, limit: int
    ) -> Sequence[ExecutionRecord]: ...


class CheckpointPort(Protocol):
    async def put(
        self,
        checkpoint: CheckpointRecord,
        fence: LeaseFence,
        *,
        expected_sequence: int,
    ) -> CheckpointRecord: ...

    async def latest(
        self, tenant_id: str, task_id: str, thread_id: str
    ) -> CheckpointRecord | None: ...


class LeasePort(Protocol):
    async def acquire(
        self,
        tenant_id: str,
        task_id: str,
        holder_id: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseFence: ...

    async def renew(
        self,
        fence: LeaseFence,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseFence: ...

    async def release(self, fence: LeaseFence) -> None: ...

    async def assert_fence(self, fence: LeaseFence, *, now: datetime) -> None: ...


class OutboxPort(Protocol):
    async def append(self, event: OutboxEvent) -> OutboxDelivery: ...

    async def unpublished(
        self, tenant_id: str, *, now: datetime, limit: int
    ) -> Sequence[OutboxDelivery]: ...

    async def mark_published(
        self, tenant_id: str, event_id: str, *, published_at: datetime
    ) -> OutboxDelivery: ...

    async def sequence_gaps(
        self, tenant_id: str, aggregate_type: str, aggregate_id: str
    ) -> Sequence[int]: ...


class ConsumerInboxPort(Protocol):
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


class CoordinationPort(Protocol):
    async def signal(self, signal: CoordinationSignal) -> None: ...

    async def remove(self, tenant_id: str, task_id: str) -> None: ...

    async def clear(self) -> None: ...

    async def rebuild(self, signals: Iterable[CoordinationSignal]) -> int: ...


class DataUnitOfWork(UnitOfWork, Protocol):
    tasks: TaskRepositoryPort
    commands: CommandInboxPort
    ledger: ExecutionLedgerPort
    checkpoints: CheckpointPort
    leases: LeasePort
    outbox: OutboxPort
    consumer_inbox: ConsumerInboxPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class DataUnitOfWorkFactory(Protocol):
    def __call__(self) -> DataUnitOfWork: ...
