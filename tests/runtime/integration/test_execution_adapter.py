from __future__ import annotations

import asyncio
from collections.abc import Callable

from flowpilot_application import (
    CommandIntakeService,
    ExecutionDisposition,
)
from flowpilot_application.testing import FakeUnitOfWorkFactory
from flowpilot_domain import TaskCommand
from flowpilot_graph import GraphStatus
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_worker import (
    InMemoryExecutionQueue,
    RuntimeExecutionAdapter,
    RuntimeWorker,
)

from tests.runtime.identity_helpers import MutableSecurityContextValidator


def test_s5_execution_port_to_worker_graph_and_fake_runtime(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
) -> None:
    async def scenario() -> None:
        queue = InMemoryExecutionQueue()
        adapter = RuntimeExecutionAdapter(queue)
        service = CommandIntakeService(
            unit_of_work=FakeUnitOfWorkFactory(),
            execution=adapter,
        )
        command = command_factory()
        acceptance = await service.accept(command)
        graph, runtime, checkpoints, leases = graph_factory()
        assert isinstance(graph, LangGraphRuntime)
        worker = RuntimeWorker(
            worker_id="worker-a",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_12345678",
        )

        worker_run = await worker.run_once()
        checkpoint = await checkpoints.load(command.tenant_id, command.task_id)

        assert (
            acceptance.execution_receipt.disposition
            is ExecutionDisposition.ACCEPTED
        )
        assert worker_run.graph_outcome is not None
        assert worker_run.graph_outcome.state.status is GraphStatus.COMPLETED
        assert checkpoint is not None
        assert checkpoint.status is GraphStatus.COMPLETED
        assert len(runtime.calls) == 1
        assert queue.acknowledged_count == 1

    asyncio.run(scenario())


def test_execution_adapter_is_idempotent_by_tenant_and_command_id(
    command_factory: Callable[..., TaskCommand],
) -> None:
    async def scenario() -> None:
        queue = InMemoryExecutionQueue()
        adapter = RuntimeExecutionAdapter(queue)
        command = command_factory()

        first = await adapter.submit(command)
        duplicate = await adapter.submit(command)

        assert first.disposition is ExecutionDisposition.ACCEPTED
        assert duplicate.disposition is ExecutionDisposition.DUPLICATE
        assert duplicate.execution_ref == first.execution_ref
        assert queue.pending_count == 1

    asyncio.run(scenario())
