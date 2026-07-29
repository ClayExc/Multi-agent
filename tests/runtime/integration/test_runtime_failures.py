from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from flowpilot_agent_runtime import FakeAgentRuntime, FakeOutcome, FakeScenario
from flowpilot_domain import TaskCommand
from flowpilot_graph import GraphStatus


def test_invalid_provider_output_maps_to_final_graph_failure(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        runtime = FakeAgentRuntime(
            default=FakeScenario(outcome=FakeOutcome.INVALID_OUTPUT),
            clock=fixed_clock,
        )
        graph, _, checkpoints, leases = graph_factory(runtime=runtime)
        command = command_factory()
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_12345678",
        )

        outcome = await graph.execute(
            command,
            execution_ref="execution://tenant-a/cmd_12345678",
            lease=lease,
        )
        checkpoint = await checkpoints.load(command.tenant_id, command.task_id)

        assert outcome.state.status is GraphStatus.FAILED
        assert outcome.should_retry is False
        assert outcome.state.failure_code == "RUNTIME_INVALID_OUTPUT"
        assert checkpoint == outcome.state

    asyncio.run(scenario())
