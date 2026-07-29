from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from .errors import GraphError, GraphErrorCode
from .ports import LeasePort, LeaseToken
from .state import GraphState


class InMemoryCheckpointStore:
    def __init__(self, *, leases: LeasePort | None = None) -> None:
        self.records: dict[tuple[str, str], GraphState] = {}
        self.write_history: list[GraphState] = []
        self.fail_writes = False
        self._leases = leases

    async def load(self, tenant_id: str, task_id: str) -> GraphState | None:
        return self.records.get((tenant_id, task_id))

    async def save(
        self,
        state: GraphState,
        *,
        expected_sequence: int,
        lease: LeaseToken,
    ) -> GraphState:
        if self._leases is not None:
            await self._leases.assert_valid(lease)
        if self.fail_writes:
            raise GraphError(
                GraphErrorCode.CHECKPOINT_UNAVAILABLE,
                "checkpoint store is unavailable",
                retryable=True,
            )
        current = self.records.get((state.tenant_id, state.task_id))
        actual_sequence = current.checkpoint_sequence if current else 0
        if actual_sequence != expected_sequence:
            raise GraphError(
                GraphErrorCode.CHECKPOINT_CONFLICT,
                "checkpoint sequence does not match",
            )
        if (
            lease.tenant_id != state.tenant_id
            or lease.task_id != state.task_id
            or lease.run_generation != state.run_generation
            or lease.run_id != state.run_id
        ):
            raise GraphError(
                GraphErrorCode.LEASE_LOST,
                "checkpoint write is not fenced by the active run",
            )
        saved = replace(state, checkpoint_sequence=actual_sequence + 1)
        self.records[(state.tenant_id, state.task_id)] = saved
        self.write_history.append(saved)
        return saved


class InMemoryLeaseStore:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = timedelta(minutes=1),
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl
        self._active: dict[tuple[str, str], LeaseToken] = {}
        self._generation: dict[tuple[str, str], int] = {}
        self._fencing = 0

    async def acquire(
        self,
        tenant_id: str,
        task_id: str,
        run_id: str,
    ) -> LeaseToken:
        key = (tenant_id, task_id)
        now = self._clock().astimezone(UTC)
        current = self._active.get(key)
        if current is not None and current.expires_at > now:
            if current.run_id == run_id:
                return current
            raise GraphError(
                GraphErrorCode.LEASE_CONFLICT,
                "task already has an active worker lease",
                retryable=True,
            )
        generation = self._generation.get(key, 0) + 1
        self._generation[key] = generation
        self._fencing += 1
        lease = LeaseToken(
            tenant_id=tenant_id,
            task_id=task_id,
            run_id=run_id,
            run_generation=generation,
            fencing_token=f"fence_{self._fencing}",
            acquired_at=now,
            expires_at=now + self._ttl,
        )
        self._active[key] = lease
        return lease

    async def assert_valid(self, lease: LeaseToken) -> None:
        current = self._active.get((lease.tenant_id, lease.task_id))
        now = self._clock().astimezone(UTC)
        if current != lease or lease.expires_at <= now:
            raise GraphError(
                GraphErrorCode.LEASE_LOST,
                "worker lease is no longer active",
            )

    async def release(self, lease: LeaseToken) -> None:
        key = (lease.tenant_id, lease.task_id)
        if self._active.get(key) == lease:
            del self._active[key]

    def force_expire(self, tenant_id: str, task_id: str) -> None:
        key = (tenant_id, task_id)
        current = self._active.get(key)
        if current is not None:
            now = self._clock().astimezone(UTC)
            self._active[key] = replace(
                current,
                acquired_at=now - timedelta(seconds=2),
                expires_at=now - timedelta(seconds=1),
            )
