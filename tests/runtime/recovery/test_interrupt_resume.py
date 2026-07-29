from __future__ import annotations

import asyncio
from collections.abc import Callable

from flowpilot_domain import TaskCommand
from flowpilot_graph import GraphNode, GraphState, GraphStatus


def test_interrupt_has_no_runtime_side_effect_and_resume_rebuilds_context(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        graph, runtime, checkpoints, leases = graph_factory()
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_12345678",
        )
        running = GraphState(
            task_id=command.task_id,
            tenant_id=command.tenant_id,
            command_id=command.command_id,
            command_digest=command.command_digest,
            run_id=lease.run_id,
            run_generation=lease.run_generation,
            graph_version="graph-v1",
            status=GraphStatus.RUNNING,
            node=GraphNode.BUILD_CONTEXT,
            security_context_ref=command.security_context.context_ref,
            security_context_hash=command.security_context.context_hash,
            purpose=command.security_context.purpose,
        )
        running = await checkpoints.save(
            running,
            expected_sequence=0,
            lease=lease,
        )

        waiting = await graph.interrupt_for_user_input(
            running,
            request_id="input-12345678",
            lease=lease,
        )

        assert waiting.status is GraphStatus.WAITING_USER
        assert waiting.node is GraphNode.INTERRUPT
        assert len(runtime.calls) == 0

        resumed = await graph.execute(
            command,
            execution_ref="execution://tenant-a/cmd_12345678",
            lease=lease,
        )

        assert resumed.state.status is GraphStatus.COMPLETED
        assert resumed.state.context_id is not None
        assert len(runtime.calls) == 1

    asyncio.run(scenario())
