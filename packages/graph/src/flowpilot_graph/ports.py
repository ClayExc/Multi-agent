from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .state import GraphState


@dataclass(frozen=True, slots=True)
class LeaseToken:
    tenant_id: str
    task_id: str
    run_id: str
    run_generation: int
    fencing_token: str
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.tenant_id,
                self.task_id,
                self.run_id,
                self.fencing_token,
            )
        ):
            raise ValueError("lease identity fields must be non-empty")
        if self.run_generation < 1:
            raise ValueError("lease run_generation must be positive")
        if (
            self.acquired_at.tzinfo is None
            or self.acquired_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("lease timestamps must be timezone-aware")
        acquired_at = self.acquired_at.astimezone(UTC)
        expires_at = self.expires_at.astimezone(UTC)
        if expires_at <= acquired_at:
            raise ValueError("lease must expire after acquisition")
        object.__setattr__(self, "acquired_at", acquired_at)
        object.__setattr__(self, "expires_at", expires_at)


class CheckpointPort(Protocol):
    async def load(self, tenant_id: str, task_id: str) -> GraphState | None: ...

    async def save(
        self,
        state: GraphState,
        *,
        expected_sequence: int,
        lease: LeaseToken,
    ) -> GraphState: ...


class LeasePort(Protocol):
    async def acquire(
        self,
        tenant_id: str,
        task_id: str,
        run_id: str,
    ) -> LeaseToken: ...

    async def assert_valid(self, lease: LeaseToken) -> None: ...

    async def release(self, lease: LeaseToken) -> None: ...
