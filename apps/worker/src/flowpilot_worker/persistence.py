from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from flowpilot_domain import Task
from flowpilot_graph import (
    CheckpointPort,
    GraphError,
    GraphErrorCode,
    GraphState,
    LeasePort,
    LeaseToken,
)
from flowpilot_persistence import (
    CheckpointRecord,
    DataUnitOfWork,
    DataUnitOfWorkFactory,
    LeaseFence,
    PersistenceError,
    PersistenceErrorCode,
)

_THREAD_ID = re.compile(r"^thread_[A-Za-z0-9_-]{8,128}$")


class _TaskProjectionPort(Protocol):
    async def get(self, tenant_id: str, task_id: str) -> Task | None: ...


@dataclass(frozen=True, slots=True)
class PersistenceRuntimeConfig:
    lease_ttl: timedelta = timedelta(minutes=1)

    def __post_init__(self) -> None:
        if self.lease_ttl <= timedelta(0):
            raise ValueError("runtime lease_ttl must be positive")


class PersistenceLeaseAdapter(LeasePort):
    """Map the Graph lease boundary onto the S6 fenced lease port."""

    def __init__(
        self,
        unit_of_work: DataUnitOfWorkFactory,
        *,
        config: PersistenceRuntimeConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._config = config or PersistenceRuntimeConfig()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def acquire(
        self,
        tenant_id: str,
        task_id: str,
        run_id: str,
    ) -> LeaseToken:
        try:
            async with self._unit_of_work() as unit_of_work:
                fence = await unit_of_work.leases.acquire(
                    tenant_id,
                    task_id,
                    run_id,
                    now=self._now(),
                    ttl=self._config.lease_ttl,
                )
                await unit_of_work.commit()
            return _lease_from_fence(fence)
        except PersistenceError as exc:
            raise _map_persistence_error(exc, operation="lease") from None
        except Exception:
            raise _storage_unavailable("worker lease could not be acquired") from None

    async def assert_valid(self, lease: LeaseToken) -> None:
        try:
            async with self._unit_of_work() as unit_of_work:
                await unit_of_work.leases.assert_fence(
                    _fence_from_lease(lease),
                    now=self._now(),
                )
        except PersistenceError as exc:
            raise _map_persistence_error(exc, operation="lease") from None
        except Exception:
            raise _storage_unavailable("worker lease could not be verified") from None

    async def release(self, lease: LeaseToken) -> None:
        try:
            async with self._unit_of_work() as unit_of_work:
                await unit_of_work.leases.release(_fence_from_lease(lease))
                await unit_of_work.commit()
        except PersistenceError as exc:
            if exc.code in {
                PersistenceErrorCode.LEASE_LOST,
                PersistenceErrorCode.STALE_FENCE,
            }:
                return
            raise _map_persistence_error(exc, operation="lease") from None
        except Exception:
            raise _storage_unavailable("worker lease could not be released") from None

    def _now(self) -> datetime:
        return _utc(self._clock(), "clock")


class PersistenceCheckpointAdapter(CheckpointPort):
    """Map GraphState onto S6 records without reversing package ownership."""

    def __init__(
        self,
        unit_of_work: DataUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock or (lambda: datetime.now(UTC))

    async def load(self, tenant_id: str, task_id: str) -> GraphState | None:
        try:
            async with self._unit_of_work() as unit_of_work:
                thread_id = await _resolve_thread(
                    unit_of_work,
                    tenant_id,
                    task_id,
                )
                record = await unit_of_work.checkpoints.latest(
                    tenant_id,
                    task_id,
                    thread_id,
                )
        except GraphError:
            raise
        except PersistenceError as exc:
            raise _map_persistence_error(exc, operation="checkpoint") from None
        except Exception:
            raise _storage_unavailable("checkpoint could not be loaded") from None
        if record is None:
            return None
        return _state_from_record(
            record,
            tenant_id=tenant_id,
            task_id=task_id,
            thread_id=thread_id,
        )

    async def save(
        self,
        state: GraphState,
        *,
        expected_sequence: int,
        lease: LeaseToken,
    ) -> GraphState:
        _assert_save_binding(state, expected_sequence, lease)
        persisted_state = replace(
            state,
            checkpoint_sequence=expected_sequence + 1,
        )
        try:
            observed_at = _utc(self._clock(), "clock")
            async with self._unit_of_work() as unit_of_work:
                thread_id = await _resolve_thread(
                    unit_of_work,
                    state.tenant_id,
                    state.task_id,
                )
                fence = _fence_from_lease(lease)
                await unit_of_work.leases.assert_fence(
                    fence,
                    now=observed_at,
                )
                record = CheckpointRecord(
                    checkpoint_id=_checkpoint_id(
                        persisted_state,
                        thread_id=thread_id,
                    ),
                    tenant_id=state.tenant_id,
                    task_id=state.task_id,
                    thread_id=thread_id,
                    run_generation=state.run_generation,
                    checkpoint_sequence=expected_sequence,
                    graph_version=state.graph_version,
                    state=persisted_state.to_checkpoint(),
                    security_context_ref=state.security_context_ref,
                    security_context_hash=state.security_context_hash,
                    created_at=observed_at,
                )
                stored = await unit_of_work.checkpoints.put(
                    record,
                    fence,
                    expected_sequence=expected_sequence,
                )
                restored = _state_from_record(
                    stored,
                    tenant_id=state.tenant_id,
                    task_id=state.task_id,
                    thread_id=thread_id,
                )
                await unit_of_work.commit()
        except GraphError:
            raise
        except PersistenceError as exc:
            raise _map_persistence_error(exc, operation="checkpoint") from None
        except Exception:
            raise _storage_unavailable("checkpoint could not be saved") from None
        return restored


def _lease_from_fence(fence: LeaseFence) -> LeaseToken:
    return LeaseToken(
        tenant_id=fence.tenant_id,
        task_id=fence.task_id,
        run_id=fence.holder_id,
        run_generation=fence.run_generation,
        fencing_token=fence.lease_token,
        acquired_at=fence.acquired_at,
        expires_at=fence.expires_at,
    )


def _fence_from_lease(lease: LeaseToken) -> LeaseFence:
    return LeaseFence(
        tenant_id=lease.tenant_id,
        task_id=lease.task_id,
        holder_id=lease.run_id,
        lease_token=lease.fencing_token,
        run_generation=lease.run_generation,
        acquired_at=lease.acquired_at,
        expires_at=lease.expires_at,
    )


async def _resolve_thread(
    unit_of_work: DataUnitOfWork,
    tenant_id: str,
    task_id: str,
) -> str:
    tasks = cast(_TaskProjectionPort, unit_of_work.tasks)
    task = await tasks.get(tenant_id, task_id)
    if task is None:
        raise GraphError(
            GraphErrorCode.CHECKPOINT_UNAVAILABLE,
            "task projection is unavailable for runtime recovery",
            retryable=True,
        )
    if task.tenant_id != tenant_id or task.task_id != task_id:
        raise GraphError(
            GraphErrorCode.SECURITY_BINDING_MISMATCH,
            "task projection does not match the runtime identity",
        )
    thread_id = task.thread_id
    if (
        not isinstance(thread_id, str)
        or _THREAD_ID.fullmatch(thread_id) is None
    ):
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "task projection contains an invalid thread identity",
        )
    return thread_id


def _assert_save_binding(
    state: GraphState,
    expected_sequence: int,
    lease: LeaseToken,
) -> None:
    if expected_sequence != state.checkpoint_sequence:
        raise GraphError(
            GraphErrorCode.CHECKPOINT_CONFLICT,
            "checkpoint sequence does not match the graph state",
        )
    if (
        state.tenant_id != lease.tenant_id
        or state.task_id != lease.task_id
        or state.run_id != lease.run_id
        or state.run_generation != lease.run_generation
    ):
        raise GraphError(
            GraphErrorCode.LEASE_LOST,
            "checkpoint is not bound to the active worker lease",
        )


def _checkpoint_id(state: GraphState, *, thread_id: str) -> str:
    identity = {
        "tenant_id": state.tenant_id,
        "task_id": state.task_id,
        "thread_id": thread_id,
        "run_generation": state.run_generation,
        "checkpoint_sequence": state.checkpoint_sequence,
        "state": state.to_checkpoint(),
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    suffix = hashlib.sha256(encoded).hexdigest()[:32]
    return f"checkpoint://{state.task_id}/{state.checkpoint_sequence}/{suffix}"


def _state_from_record(
    record: CheckpointRecord,
    *,
    tenant_id: str,
    task_id: str,
    thread_id: str,
) -> GraphState:
    try:
        state = GraphState.from_checkpoint(record.state)
    except GraphError:
        raise
    except Exception:
        raise GraphError(
            GraphErrorCode.STATE_INVALID,
            "stored checkpoint state is invalid",
        ) from None
    if (
        record.tenant_id != tenant_id
        or record.task_id != task_id
        or record.thread_id != thread_id
        or state.tenant_id != record.tenant_id
        or state.task_id != record.task_id
        or state.run_generation != record.run_generation
        or state.checkpoint_sequence != record.checkpoint_sequence
        or state.graph_version != record.graph_version
        or state.security_context_ref != record.security_context_ref
        or state.security_context_hash != record.security_context_hash
    ):
        raise GraphError(
            GraphErrorCode.SECURITY_BINDING_MISMATCH,
            "stored checkpoint identity does not match its trusted envelope",
        )
    return state


def _map_persistence_error(
    error: PersistenceError,
    *,
    operation: str,
) -> GraphError:
    if error.code is PersistenceErrorCode.LEASE_UNAVAILABLE:
        return GraphError(
            GraphErrorCode.LEASE_CONFLICT,
            "task already has an active worker lease",
            retryable=True,
        )
    if error.code in {
        PersistenceErrorCode.LEASE_LOST,
        PersistenceErrorCode.STALE_FENCE,
        PersistenceErrorCode.NOT_FOUND,
    }:
        return GraphError(
            GraphErrorCode.LEASE_LOST,
            "worker lease is stale or no longer active",
        )
    if error.code is PersistenceErrorCode.VERSION_CONFLICT:
        return GraphError(
            GraphErrorCode.CHECKPOINT_CONFLICT,
            "checkpoint compare-and-swap failed",
        )
    if error.code in {
        PersistenceErrorCode.TENANT_MISMATCH,
        PersistenceErrorCode.TENANT_REQUIRED,
    }:
        return GraphError(
            GraphErrorCode.SECURITY_BINDING_MISMATCH,
            "persistence identity binding was rejected",
        )
    if error.code in {
        PersistenceErrorCode.CONFLICT,
        PersistenceErrorCode.IDEMPOTENCY_CONFLICT,
    }:
        return GraphError(
            GraphErrorCode.CHECKPOINT_CONFLICT,
            "checkpoint identity is already bound to different state",
        )
    if error.code in {
        PersistenceErrorCode.DRIVER_PROTOCOL,
        PersistenceErrorCode.INVALID_TRANSITION,
        PersistenceErrorCode.SECRET_MATERIAL,
    }:
        return GraphError(
            GraphErrorCode.STATE_INVALID,
            "checkpoint state was rejected by the persistence boundary",
        )
    return _storage_unavailable(
        f"{operation} persistence boundary is unavailable",
        retryable=error.retryable,
    )


def _storage_unavailable(
    message: str,
    *,
    retryable: bool = True,
) -> GraphError:
    return GraphError(
        GraphErrorCode.CHECKPOINT_UNAVAILABLE,
        message,
        retryable=retryable,
    )


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)
