from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from flowpilot_domain import TaskCommand


@dataclass(frozen=True, slots=True)
class ExecutionEnvelope:
    execution_ref: str
    command: TaskCommand

    @property
    def key(self) -> tuple[str, str]:
        return (self.command.tenant_id, self.command.command_id)


class ExecutionQueuePort(Protocol):
    async def enqueue(self, envelope: ExecutionEnvelope) -> bool:
        """Return true only for the first tenant + command_id submission."""

    async def dequeue(self, worker_id: str) -> ExecutionEnvelope | None: ...

    async def acknowledge(
        self,
        worker_id: str,
        envelope: ExecutionEnvelope,
    ) -> None: ...

    async def retry(self, worker_id: str, envelope: ExecutionEnvelope) -> None: ...
