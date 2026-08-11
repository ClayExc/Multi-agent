from __future__ import annotations

import asyncio
from collections.abc import Callable

from flowpilot_domain import TaskCommand
from flowpilot_graph import GraphStatus
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_worker import (
    InMemoryExecutionQueue,
    RuntimeExecutionAdapter,
    RuntimeWorker,
)
from identity_helpers import MutableSecurityContextValidator


def test_state_graph_owns_runtime_node_routing(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        graph, runtime, checkpoints, leases = graph_factory()
        assert isinstance(graph, LangGraphRuntime)
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        worker = RuntimeWorker(
            worker_id="worker-langgraph",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_langgraph_12345678",
        )

        result = await worker.run_once()
        checkpoint = await checkpoints.load(
            command.tenant_id,
            command.task_id,
        )

        assert result.graph_outcome is not None
        assert result.graph_outcome.state.status is GraphStatus.COMPLETED
        assert checkpoint is not None
        assert checkpoint.status is GraphStatus.COMPLETED
        assert len(runtime.calls) == 1
        assert queue.acknowledged_count == 1

    asyncio.run(scenario())
