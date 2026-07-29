from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from flowpilot_graph import (
    GraphError,
    GraphExecutionPort,
    GraphRunOutcome,
    LeasePort,
)

from .queue import ExecutionQueuePort


@dataclass(frozen=True, slots=True)
class WorkerRun:
    worker_id: str
    execution_ref: str | None
    graph_outcome: GraphRunOutcome | None
    idle: bool


class RuntimeWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        queue: ExecutionQueuePort,
        leases: LeasePort,
        graph: GraphExecutionPort,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._queue = queue
        self._leases = leases
        self._graph = graph
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
        lease = await self._leases.acquire(
            envelope.command.tenant_id,
            envelope.command.task_id,
            self._run_id_factory(),
        )
        try:
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
            await self._leases.release(lease)
