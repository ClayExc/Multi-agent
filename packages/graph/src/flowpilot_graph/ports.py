from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .state import GraphState


@dataclass(frozen=True, slots=True)
class LeaseToken:
    tenant_id: str
    task_id: str
    run_id: str
    run_generation: int
    fencing_token: int
    expires_at: datetime


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
