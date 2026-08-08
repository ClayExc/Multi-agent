from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Self

from flowpilot_application import (
    CommandInboxPort,
    ExecutionReceipt,
    OutboxEventView,
    StoredCommand,
    TaskEventConsumerInboxPort,
    TaskEventOutboxPort,
    TaskEventUnitOfWork,
    TaskEventUnitOfWorkFactory,
    TaskQueryPort,
    TaskQueryUnitOfWork,
    TaskQueryUnitOfWorkFactory,
    TaskRepositoryPort,
    UnitOfWork,
    UnitOfWorkFactory,
    VersionSlotReservation,
)
from flowpilot_domain import Task

from .errors import PersistenceError, PersistenceErrorCode
from .models import OutboxDelivery
from .ports import (
    ConsumerInboxPort,
    DataUnitOfWork,
    DataUnitOfWorkFactory,
    OutboxPort,
    TaskPersistencePort,
)


class _TenantScope:
    """Fail closed when one application transaction attempts a tenant switch."""

    def __init__(self) -> None:
        self._tenant_id: str | None = None

    def bind(self, tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 128:
            raise PersistenceError(
                PersistenceErrorCode.TENANT_REQUIRED,
                "a bounded tenant identity is required",
            )
        if self._tenant_id is None:
            self._tenant_id = tenant_id
        elif self._tenant_id != tenant_id:
            raise PersistenceError(
                PersistenceErrorCode.TENANT_MISMATCH,
                "a transaction cannot switch tenant context",
            )


class _ApplicationTaskRepository:
    def __init__(self, inner: TaskPersistencePort, scope: _TenantScope) -> None:
        self._inner = inner
        self._scope = scope

    async def get_version(self, tenant_id: str, task_id: str) -> int | None:
        self._scope.bind(tenant_id)
        return await self._inner.get_version(tenant_id, task_id)

    async def get(self, tenant_id: str, task_id: str) -> Task | None:
        self._scope.bind(tenant_id)
        return await self._inner.get(tenant_id, task_id)


class _ApplicationCommandInbox:
    def __init__(self, inner: CommandInboxPort, scope: _TenantScope) -> None:
        self._inner = inner
        self._scope = scope

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> StoredCommand | None:
        self._scope.bind(tenant_id)
        return await self._inner.get_by_idempotency_key(
            tenant_id, idempotency_key
        )

    async def get_by_command_id(
        self, tenant_id: str, command_id: str
    ) -> StoredCommand | None:
        self._scope.bind(tenant_id)
        return await self._inner.get_by_command_id(tenant_id, command_id)

    async def reserve_version_slot(
        self,
        tenant_id: str,
        task_id: str,
        expected_task_version: int | None,
        command_id: str,
    ) -> VersionSlotReservation:
        self._scope.bind(tenant_id)
        return await self._inner.reserve_version_slot(
            tenant_id,
            task_id,
            expected_task_version,
            command_id,
        )

    async def add(self, stored: StoredCommand) -> None:
        self._scope.bind(stored.command.tenant_id)
        await self._inner.add(stored)

    async def record_execution(
        self,
        tenant_id: str,
        command_id: str,
        receipt: ExecutionReceipt,
    ) -> StoredCommand:
        self._scope.bind(tenant_id)
        return await self._inner.record_execution(
            tenant_id,
            command_id,
            receipt,
        )


class _ApplicationTaskEventOutbox:
    def __init__(self, inner: OutboxPort, scope: _TenantScope) -> None:
        self._inner = inner
        self._scope = scope

    async def unpublished(
        self, tenant_id: str, *, now: datetime, limit: int
    ) -> Sequence[OutboxEventView]:
        self._scope.bind(tenant_id)
        deliveries = await self._inner.unpublished(
            tenant_id,
            now=now,
            limit=limit,
        )
        return tuple(_event_view(delivery) for delivery in deliveries)

    async def mark_published(
        self, tenant_id: str, event_id: str, *, published_at: datetime
    ) -> OutboxEventView:
        self._scope.bind(tenant_id)
        delivery = await self._inner.mark_published(
            tenant_id,
            event_id,
            published_at=published_at,
        )
        return _event_view(delivery)

    async def sequence_gaps(
        self,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
    ) -> Sequence[int]:
        self._scope.bind(tenant_id)
        return await self._inner.sequence_gaps(
            tenant_id,
            aggregate_type,
            aggregate_id,
        )


class _ApplicationTaskEventConsumerInbox:
    def __init__(self, inner: ConsumerInboxPort, scope: _TenantScope) -> None:
        self._inner = inner
        self._scope = scope

    async def accept_once(
        self,
        tenant_id: str,
        consumer_id: str,
        event_id: str,
        payload_hash: str,
        *,
        processed_at: datetime,
    ) -> bool:
        self._scope.bind(tenant_id)
        return await self._inner.accept_once(
            tenant_id,
            consumer_id,
            event_id,
            payload_hash,
            processed_at=processed_at,
        )


def _event_view(delivery: OutboxDelivery) -> OutboxEventView:
    event = delivery.event
    return OutboxEventView(
        event_id=event.event_id,
        tenant_id=event.tenant_id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        sequence=event.sequence,
        event_type=event.event_type,
        payload=event.payload,
        occurred_at=event.occurred_at,
        available_at=event.available_at,
    )


class _ApplicationCommandUnitOfWork:
    def __init__(self, inner: DataUnitOfWork) -> None:
        self._inner = inner
        self.tasks: TaskRepositoryPort
        self.commands: CommandInboxPort

    async def __aenter__(self) -> Self:
        entered = await self._inner.__aenter__()
        scope = _TenantScope()
        self.tasks = _ApplicationTaskRepository(entered.tasks, scope)
        self.commands = _ApplicationCommandInbox(entered.commands, scope)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc, traceback)

    async def commit(self) -> None:
        await self._inner.commit()


class _ApplicationTaskQueryUnitOfWork:
    def __init__(self, inner: DataUnitOfWork) -> None:
        self._inner = inner
        self.tasks: TaskQueryPort

    async def __aenter__(self) -> Self:
        entered = await self._inner.__aenter__()
        self.tasks = _ApplicationTaskRepository(entered.tasks, _TenantScope())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc, traceback)


class _ApplicationTaskEventUnitOfWork:
    def __init__(self, inner: DataUnitOfWork) -> None:
        self._inner = inner
        self.tasks: TaskQueryPort
        self.outbox: TaskEventOutboxPort
        self.consumer_inbox: TaskEventConsumerInboxPort

    async def __aenter__(self) -> Self:
        entered = await self._inner.__aenter__()
        scope = _TenantScope()
        self.tasks = _ApplicationTaskRepository(entered.tasks, scope)
        self.outbox = _ApplicationTaskEventOutbox(entered.outbox, scope)
        self.consumer_inbox = _ApplicationTaskEventConsumerInbox(
            entered.consumer_inbox,
            scope,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc, traceback)

    async def commit(self) -> None:
        await self._inner.commit()


class _CommandUnitOfWorkFactory:
    def __init__(self, inner: DataUnitOfWorkFactory) -> None:
        self._inner = inner

    def __call__(self) -> UnitOfWork:
        return _ApplicationCommandUnitOfWork(self._inner())


class _TaskQueryUnitOfWorkFactory:
    def __init__(self, inner: DataUnitOfWorkFactory) -> None:
        self._inner = inner

    def __call__(self) -> TaskQueryUnitOfWork:
        return _ApplicationTaskQueryUnitOfWork(self._inner())


class _TaskEventUnitOfWorkFactory:
    def __init__(self, inner: DataUnitOfWorkFactory) -> None:
        self._inner = inner

    def __call__(self) -> TaskEventUnitOfWork:
        return _ApplicationTaskEventUnitOfWork(self._inner())


@dataclass(frozen=True, slots=True)
class ApplicationUnitOfWorkFactories:
    """S6 adapters for the three S5 application transaction capabilities."""

    command_unit_of_work: UnitOfWorkFactory
    task_query_unit_of_work: TaskQueryUnitOfWorkFactory
    task_event_unit_of_work: TaskEventUnitOfWorkFactory


def compose_application_unit_of_work_factories(
    data_unit_of_work: DataUnitOfWorkFactory,
) -> ApplicationUnitOfWorkFactories:
    """Expose least-capability S5 ports over one durable S6 UoW factory.

    Every protocol call creates a fresh underlying transaction. Task-event
    reads, consumer deduplication and publish acknowledgement share one tenant
    binding and commit together within each event UoW.
    """

    return ApplicationUnitOfWorkFactories(
        command_unit_of_work=_CommandUnitOfWorkFactory(data_unit_of_work),
        task_query_unit_of_work=_TaskQueryUnitOfWorkFactory(data_unit_of_work),
        task_event_unit_of_work=_TaskEventUnitOfWorkFactory(data_unit_of_work),
    )
