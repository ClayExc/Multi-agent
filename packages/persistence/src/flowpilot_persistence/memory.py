from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import uuid4

from flowpilot_application import (
    ExecutionReceipt,
    StoredCommand,
    VersionSlotReservation,
)

from .errors import PersistenceError, PersistenceErrorCode
from .models import (
    CheckpointRecord,
    ExecutionIntent,
    ExecutionOutcome,
    ExecutionRecord,
    LeaseFence,
    LedgerStatus,
    OutboxDelivery,
    OutboxEvent,
    RetryBasis,
    require_sha256,
    utc,
)

Clock = Callable[[], datetime]

_LEDGER_TRANSITIONS: dict[LedgerStatus, frozenset[LedgerStatus]] = {
    LedgerStatus.PREPARED: frozenset({LedgerStatus.RUNNING}),
    LedgerStatus.RUNNING: frozenset(
        {
            LedgerStatus.SUCCEEDED,
            LedgerStatus.VERIFIED,
            LedgerStatus.FAILED_RETRYABLE,
            LedgerStatus.FAILED_FINAL,
            LedgerStatus.UNKNOWN,
        }
    ),
    LedgerStatus.SUCCEEDED: frozenset(
        {
            LedgerStatus.VERIFIED,
            LedgerStatus.FAILED_FINAL,
            LedgerStatus.UNKNOWN,
        }
    ),
    LedgerStatus.VERIFIED: frozenset(),
    LedgerStatus.FAILED_RETRYABLE: frozenset({LedgerStatus.RUNNING}),
    LedgerStatus.FAILED_FINAL: frozenset(),
    LedgerStatus.UNKNOWN: frozenset(
        {
            LedgerStatus.VERIFIED,
            LedgerStatus.FAILED_RETRYABLE,
            LedgerStatus.FAILED_FINAL,
        }
    ),
}


@dataclass(slots=True)
class _Snapshot:
    task_versions: dict[tuple[str, str], int] = field(default_factory=dict)
    commands_by_id: dict[tuple[str, str], StoredCommand] = field(
        default_factory=dict
    )
    command_id_by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    version_slots: dict[tuple[str, str, int | None], str] = field(
        default_factory=dict
    )
    executions_by_id: dict[tuple[str, str], ExecutionRecord] = field(
        default_factory=dict
    )
    execution_id_by_key: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )
    checkpoints: dict[tuple[str, str, str], CheckpointRecord] = field(
        default_factory=dict
    )
    leases: dict[tuple[str, str], LeaseFence] = field(default_factory=dict)
    outbox_by_id: dict[tuple[str, str], OutboxDelivery] = field(
        default_factory=dict
    )
    outbox_id_by_sequence: dict[tuple[str, str, str, int], str] = field(
        default_factory=dict
    )
    consumer_inbox: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )

    def clone(self) -> _Snapshot:
        return _Snapshot(
            task_versions=dict(self.task_versions),
            commands_by_id=dict(self.commands_by_id),
            command_id_by_key=dict(self.command_id_by_key),
            version_slots=dict(self.version_slots),
            executions_by_id=dict(self.executions_by_id),
            execution_id_by_key=dict(self.execution_id_by_key),
            checkpoints=dict(self.checkpoints),
            leases=dict(self.leases),
            outbox_by_id=dict(self.outbox_by_id),
            outbox_id_by_sequence=dict(self.outbox_id_by_sequence),
            consumer_inbox=dict(self.consumer_inbox),
        )


@dataclass(slots=True)
class MemoryDatabase:
    """Deterministic transaction fixture; never a production fact source."""

    state: _Snapshot = field(default_factory=_Snapshot)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def seed_task_version(self, tenant_id: str, task_id: str, version: int) -> None:
        if version < 0:
            raise ValueError("version cannot be negative")
        self.state.task_versions[(tenant_id, task_id)] = version


class MemoryTaskRepository:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    async def get_version(self, tenant_id: str, task_id: str) -> int | None:
        return self._snapshot.task_versions.get((tenant_id, task_id))


class MemoryCommandInbox:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> StoredCommand | None:
        command_id = self._snapshot.command_id_by_key.get(
            (tenant_id, idempotency_key)
        )
        if command_id is None:
            return None
        return self._snapshot.commands_by_id[(tenant_id, command_id)]

    async def get_by_command_id(
        self, tenant_id: str, command_id: str
    ) -> StoredCommand | None:
        return self._snapshot.commands_by_id.get((tenant_id, command_id))

    async def reserve_version_slot(
        self,
        tenant_id: str,
        task_id: str,
        expected_task_version: int | None,
        command_id: str,
    ) -> VersionSlotReservation:
        slot = (tenant_id, task_id, expected_task_version)
        owner = self._snapshot.version_slots.get(slot)
        if owner is not None and owner != command_id:
            return VersionSlotReservation.CONFLICT
        self._snapshot.version_slots[slot] = command_id
        return VersionSlotReservation.RESERVED

    async def add(self, stored: StoredCommand) -> None:
        command = stored.command
        id_key = (command.tenant_id, command.command_id)
        idem_key = (command.tenant_id, command.idempotency_key)
        if id_key in self._snapshot.commands_by_id:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "command_id is already stored",
            )
        if idem_key in self._snapshot.command_id_by_key:
            raise PersistenceError(
                PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
                "idempotency key is already stored",
            )
        self._snapshot.commands_by_id[id_key] = stored
        self._snapshot.command_id_by_key[idem_key] = command.command_id

    async def record_execution(
        self, tenant_id: str, command_id: str, receipt: ExecutionReceipt
    ) -> StoredCommand:
        key = (tenant_id, command_id)
        stored = self._snapshot.commands_by_id.get(key)
        if stored is None:
            raise PersistenceError(
                PersistenceErrorCode.NOT_FOUND,
                "command was not found",
            )
        if (
            receipt.tenant_id != tenant_id
            or receipt.command_id != command_id
            or receipt.task_id != stored.command.task_id
        ):
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "execution receipt does not match the stored command",
            )
        if stored.execution_receipt is not None:
            if stored.execution_receipt != receipt:
                raise PersistenceError(
                    PersistenceErrorCode.CONFLICT,
                    "execution receipt is immutable",
                )
            return stored
        updated = replace(stored, execution_receipt=receipt)
        self._snapshot.commands_by_id[key] = updated
        return updated


class MemoryExecutionLedger:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    async def prepare(self, intent: ExecutionIntent) -> ExecutionRecord:
        identity = (intent.tenant_id, intent.tool_execution_id)
        idem = (intent.tenant_id, intent.tool_name, intent.idempotency_key)
        existing_id = self._snapshot.executions_by_id.get(identity)
        keyed_id = self._snapshot.execution_id_by_key.get(idem)
        existing = existing_id
        if existing is None and keyed_id is not None:
            existing = self._snapshot.executions_by_id[
                (intent.tenant_id, keyed_id)
            ]
        if existing is not None:
            if existing.intent.fingerprint() != intent.fingerprint():
                raise PersistenceError(
                    PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
                    "execution identity is bound to another immutable action",
                )
            return existing
        record = ExecutionRecord(
            intent=intent,
            status=LedgerStatus.PREPARED,
            attempt_count=0,
            updated_at=intent.created_at,
        )
        self._snapshot.executions_by_id[identity] = record
        self._snapshot.execution_id_by_key[idem] = intent.tool_execution_id
        return record

    async def get(
        self, tenant_id: str, tool_execution_id: str
    ) -> ExecutionRecord | None:
        return self._snapshot.executions_by_id.get(
            (tenant_id, tool_execution_id)
        )

    async def mark_running(
        self,
        tenant_id: str,
        tool_execution_id: str,
        *,
        now: datetime,
    ) -> ExecutionRecord:
        record = self._required(tenant_id, tool_execution_id)
        self._assert_transition(record.status, LedgerStatus.RUNNING)
        updated = replace(
            record,
            status=LedgerStatus.RUNNING,
            attempt_count=record.attempt_count + 1,
            updated_at=utc(now, "now"),
            outcome=None,
        )
        self._snapshot.executions_by_id[(tenant_id, tool_execution_id)] = updated
        return updated

    async def record_outcome(
        self,
        tenant_id: str,
        tool_execution_id: str,
        outcome: ExecutionOutcome,
    ) -> ExecutionRecord:
        record = self._required(tenant_id, tool_execution_id)
        self._assert_transition(record.status, outcome.status)
        if (
            record.status is LedgerStatus.UNKNOWN
            and outcome.status is LedgerStatus.FAILED_RETRYABLE
            and outcome.retry_basis is not RetryBasis.CONFIRMED_NOT_EXECUTED
        ):
            raise PersistenceError(
                PersistenceErrorCode.RECONCILIATION_REQUIRED,
                "unknown execution requires authoritative not-executed evidence",
            )
        updated = replace(
            record,
            status=outcome.status,
            updated_at=outcome.recorded_at,
            outcome=outcome,
        )
        self._snapshot.executions_by_id[(tenant_id, tool_execution_id)] = updated
        return updated

    async def pending_reconciliation(
        self, tenant_id: str, *, limit: int
    ) -> Sequence[ExecutionRecord]:
        if limit < 1:
            return ()
        records = [
            record
            for (record_tenant, _), record in self._snapshot.executions_by_id.items()
            if record_tenant == tenant_id and record.status is LedgerStatus.UNKNOWN
        ]
        records.sort(key=lambda item: (item.updated_at, item.intent.tool_execution_id))
        return tuple(records[:limit])

    def _required(self, tenant_id: str, tool_execution_id: str) -> ExecutionRecord:
        record = self._snapshot.executions_by_id.get(
            (tenant_id, tool_execution_id)
        )
        if record is None:
            raise PersistenceError(
                PersistenceErrorCode.NOT_FOUND,
                "execution record was not found",
            )
        return record

    @staticmethod
    def _assert_transition(source: LedgerStatus, target: LedgerStatus) -> None:
        if target not in _LEDGER_TRANSITIONS[source]:
            code = (
                PersistenceErrorCode.RECONCILIATION_REQUIRED
                if source is LedgerStatus.UNKNOWN and target is LedgerStatus.RUNNING
                else PersistenceErrorCode.INVALID_TRANSITION
            )
            raise PersistenceError(
                code,
                f"ledger transition {source.value}->{target.value} is not allowed",
            )


class MemoryLeaseRepository:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    async def acquire(
        self,
        tenant_id: str,
        task_id: str,
        holder_id: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseFence:
        normalized = utc(now, "now")
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        key = (tenant_id, task_id)
        existing = self._snapshot.leases.get(key)
        if existing is not None and existing.is_active(normalized):
            if existing.holder_id == holder_id:
                return existing
            raise PersistenceError(
                PersistenceErrorCode.LEASE_UNAVAILABLE,
                "task already has an active worker lease",
                retryable=True,
            )
        generation = 1 if existing is None else existing.run_generation + 1
        fence = LeaseFence(
            tenant_id=tenant_id,
            task_id=task_id,
            holder_id=holder_id,
            lease_token=f"lease_{uuid4().hex}",
            run_generation=generation,
            acquired_at=normalized,
            expires_at=normalized + ttl,
        )
        self._snapshot.leases[key] = fence
        return fence

    async def renew(
        self,
        fence: LeaseFence,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseFence:
        normalized = utc(now, "now")
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        await self.assert_fence(fence, now=normalized)
        renewed = replace(fence, expires_at=normalized + ttl)
        self._snapshot.leases[(fence.tenant_id, fence.task_id)] = renewed
        return renewed

    async def release(self, fence: LeaseFence) -> None:
        current = self._snapshot.leases.get((fence.tenant_id, fence.task_id))
        if current != fence:
            raise PersistenceError(
                PersistenceErrorCode.LEASE_LOST,
                "worker lease is no longer owned by this fence",
            )
        del self._snapshot.leases[(fence.tenant_id, fence.task_id)]

    async def assert_fence(self, fence: LeaseFence, *, now: datetime) -> None:
        current = self._snapshot.leases.get((fence.tenant_id, fence.task_id))
        if (
            current is None
            or current.lease_token != fence.lease_token
            or current.run_generation != fence.run_generation
            or current.holder_id != fence.holder_id
            or not current.is_active(now)
        ):
            raise PersistenceError(
                PersistenceErrorCode.STALE_FENCE,
                "worker fence is stale or expired",
            )


class MemoryCheckpointRepository:
    def __init__(
        self, snapshot: _Snapshot, leases: MemoryLeaseRepository
    ) -> None:
        self._snapshot = snapshot
        self._leases = leases

    async def put(
        self, checkpoint: CheckpointRecord, fence: LeaseFence
    ) -> CheckpointRecord:
        if (
            checkpoint.tenant_id != fence.tenant_id
            or checkpoint.task_id != fence.task_id
            or checkpoint.run_generation != fence.run_generation
        ):
            raise PersistenceError(
                PersistenceErrorCode.STALE_FENCE,
                "checkpoint does not match the worker fence",
            )
        await self._leases.assert_fence(fence, now=checkpoint.created_at)
        key = (
            checkpoint.tenant_id,
            checkpoint.thread_id,
            checkpoint.checkpoint_id,
        )
        existing = self._snapshot.checkpoints.get(key)
        if existing is not None and existing != checkpoint:
            raise PersistenceError(
                PersistenceErrorCode.CONFLICT,
                "checkpoint_id is immutable",
            )
        self._snapshot.checkpoints[key] = checkpoint
        return checkpoint

    async def latest(
        self, tenant_id: str, thread_id: str
    ) -> CheckpointRecord | None:
        candidates = [
            checkpoint
            for (record_tenant, record_thread, _), checkpoint in (
                self._snapshot.checkpoints.items()
            )
            if record_tenant == tenant_id and record_thread == thread_id
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.run_generation,
                item.created_at,
                item.checkpoint_id,
            ),
        )


class MemoryOutboxRepository:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    async def append(self, event: OutboxEvent) -> OutboxDelivery:
        id_key = (event.tenant_id, event.event_id)
        sequence_key = (
            event.tenant_id,
            event.aggregate_type,
            event.aggregate_id,
            event.sequence,
        )
        existing = self._snapshot.outbox_by_id.get(id_key)
        if existing is not None:
            if existing.event.fingerprint() != event.fingerprint():
                raise PersistenceError(
                    PersistenceErrorCode.CONFLICT,
                    "event_id is bound to another outbox event",
                )
            return existing
        sequence_owner = self._snapshot.outbox_id_by_sequence.get(sequence_key)
        if sequence_owner is not None:
            raise PersistenceError(
                PersistenceErrorCode.VERSION_CONFLICT,
                "outbox sequence is already occupied",
            )
        delivery = OutboxDelivery(event=event)
        self._snapshot.outbox_by_id[id_key] = delivery
        self._snapshot.outbox_id_by_sequence[sequence_key] = event.event_id
        return delivery

    async def unpublished(
        self, tenant_id: str, *, now: datetime, limit: int
    ) -> Sequence[OutboxDelivery]:
        normalized = utc(now, "now")
        if limit < 1:
            return ()
        deliveries = [
            delivery
            for (record_tenant, _), delivery in self._snapshot.outbox_by_id.items()
            if (
                record_tenant == tenant_id
                and delivery.published_at is None
                and delivery.event.available_at <= normalized
            )
        ]
        deliveries.sort(
            key=lambda item: (
                item.event.available_at,
                item.event.aggregate_type,
                item.event.aggregate_id,
                item.event.sequence,
            )
        )
        return tuple(deliveries[:limit])

    async def mark_published(
        self, tenant_id: str, event_id: str, *, published_at: datetime
    ) -> OutboxDelivery:
        key = (tenant_id, event_id)
        delivery = self._snapshot.outbox_by_id.get(key)
        if delivery is None:
            raise PersistenceError(
                PersistenceErrorCode.NOT_FOUND,
                "outbox event was not found",
            )
        if delivery.published_at is not None:
            return delivery
        updated = replace(
            delivery,
            publish_attempts=delivery.publish_attempts + 1,
            published_at=utc(published_at, "published_at"),
        )
        self._snapshot.outbox_by_id[key] = updated
        return updated

    async def sequence_gaps(
        self, tenant_id: str, aggregate_type: str, aggregate_id: str
    ) -> Sequence[int]:
        sequences = sorted(
            sequence
            for (
                record_tenant,
                record_type,
                record_id,
                sequence,
            ) in self._snapshot.outbox_id_by_sequence
            if (
                record_tenant == tenant_id
                and record_type == aggregate_type
                and record_id == aggregate_id
            )
        )
        if not sequences:
            return ()
        present = set(sequences)
        return tuple(
            sequence
            for sequence in range(1, sequences[-1] + 1)
            if sequence not in present
        )


class MemoryConsumerInbox:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    async def accept_once(
        self,
        tenant_id: str,
        consumer_id: str,
        event_id: str,
        payload_hash: str,
        *,
        processed_at: datetime,
    ) -> bool:
        del processed_at
        require_sha256(payload_hash, "payload_hash")
        key = (tenant_id, consumer_id, event_id)
        existing = self._snapshot.consumer_inbox.get(key)
        if existing is None:
            self._snapshot.consumer_inbox[key] = payload_hash
            return True
        if existing != payload_hash:
            raise PersistenceError(
                PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
                "redelivered event payload does not match its inbox record",
            )
        return False


class MemoryDataUnitOfWork:
    def __init__(
        self,
        database: MemoryDatabase,
    ) -> None:
        self._database = database
        self._working: _Snapshot | None = None
        self._committed = False
        self.tasks: MemoryTaskRepository
        self.commands: MemoryCommandInbox
        self.ledger: MemoryExecutionLedger
        self.leases: MemoryLeaseRepository
        self.checkpoints: MemoryCheckpointRepository
        self.outbox: MemoryOutboxRepository
        self.consumer_inbox: MemoryConsumerInbox

    async def __aenter__(self) -> Self:
        await self._database.lock.acquire()
        self._working = self._database.state.clone()
        self.tasks = MemoryTaskRepository(self._working)
        self.commands = MemoryCommandInbox(self._working)
        self.ledger = MemoryExecutionLedger(self._working)
        self.leases = MemoryLeaseRepository(self._working)
        self.checkpoints = MemoryCheckpointRepository(self._working, self.leases)
        self.outbox = MemoryOutboxRepository(self._working)
        self.consumer_inbox = MemoryConsumerInbox(self._working)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        try:
            if exc_type is None and self._committed and self._working is not None:
                self._database.state = self._working
        finally:
            self._working = None
            self._database.lock.release()

    async def commit(self) -> None:
        if self._working is None:
            raise RuntimeError("unit of work has not been entered")
        self._committed = True


class MemoryDataUnitOfWorkFactory:
    def __init__(self, database: MemoryDatabase | None = None) -> None:
        self.database = database or MemoryDatabase()

    def __call__(self) -> MemoryDataUnitOfWork:
        return MemoryDataUnitOfWork(self.database)
