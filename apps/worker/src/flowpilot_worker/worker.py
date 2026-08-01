from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from flowpilot_domain import DomainViolation, TaskCommand
from flowpilot_graph import (
    GraphError,
    GraphErrorCode,
    GraphExecutionPort,
    GraphRunOutcome,
    LeasePort,
    LeaseToken,
)

from .queue import ExecutionQueuePort


@dataclass(frozen=True, slots=True)
class WorkerRun:
    worker_id: str
    execution_ref: str | None
    graph_outcome: GraphRunOutcome | None
    idle: bool


class ExecutionGuardPort(Protocol):
    async def validate(self, command: TaskCommand) -> None: ...


class _CommandExecutionGuard:
    async def validate(self, command: TaskCommand) -> None:
        try:
            command.assert_digest()
            command.assert_security_binding()
        except DomainViolation as exc:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "command failed deterministic worker binding",
            ) from exc


class RuntimeWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        queue: ExecutionQueuePort,
        leases: LeasePort,
        graph: GraphExecutionPort,
        execution_guard: ExecutionGuardPort | None = None,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._queue = queue
        self._leases = leases
        self._graph = graph
        self._execution_guard = execution_guard or _CommandExecutionGuard()
        self._run_id_factory = run_id_factory or (
            lambda: f"run_{uuid.uuid4().hex}"
        )

    async def run_once(self) -> WorkerRun:
        envelope = await self._queue.dequeue(self._worker_id)
        if envelope is None:
            return WorkerRun(
                worker_id=self._worker_id,
                execution_ref=None,
                graph_outcome=None,
                idle=True,
            )
        lease: LeaseToken | None = None
        try:
            await self._execution_guard.validate(envelope.command)
            lease = await self._leases.acquire(
                envelope.command.tenant_id,
                envelope.command.task_id,
                self._run_id_factory(),
            )
            await self._leases.assert_valid(lease)
            outcome = await self._graph.execute(
                envelope.command,
                execution_ref=envelope.execution_ref,
                lease=lease,
            )
            await self._leases.assert_valid(lease)
            if outcome.should_retry:
                await self._queue.retry(self._worker_id, envelope)
            else:
                await self._queue.acknowledge(self._worker_id, envelope)
            return WorkerRun(
                worker_id=self._worker_id,
                execution_ref=envelope.execution_ref,
                graph_outcome=outcome,
                idle=False,
            )
        except GraphError as exc:
            if exc.retryable:
                await self._queue.retry(self._worker_id, envelope)
            else:
                await self._queue.acknowledge(self._worker_id, envelope)
            raise
        finally:
            if lease is not None:
                await self._leases.release(lease)
