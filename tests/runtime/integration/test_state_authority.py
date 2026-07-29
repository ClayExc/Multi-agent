from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from flowpilot_agent_runtime import (
    FakeAgentRuntime,
    FakeScenario,
    ToolOperation,
    ToolProposal,
)
from flowpilot_domain import TaskCommand
from flowpilot_graph import GraphStatus


def test_model_terminal_fields_cannot_override_graph_authority(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        runtime = FakeAgentRuntime(
            default=FakeScenario(
                structured_output={
                    "status": "FAILED",
                    "terminal": True,
                    "current_node": "provider_owned_node",
                }
            ),
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

        assert outcome.state.status is GraphStatus.COMPLETED
        assert checkpoint is not None
        assert checkpoint.status is GraphStatus.COMPLETED
        assert "current_node" not in checkpoint.to_checkpoint()

    asyncio.run(scenario())


def test_tool_proposal_stays_non_authoritative_in_checkpoint(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        proposal = ToolProposal(
            proposal_id="tprop_12345678",
            tool="knowledge.search.v1",
            operation=ToolOperation.READ,
            arguments={"query": "vpn"},
            resource={"type": "knowledge"},
            purpose="it_support",
            evidence_refs=("evidence://query/1",),
        )
        runtime = FakeAgentRuntime(
            default=FakeScenario(tool_proposals=(proposal,)),
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

        assert outcome.state.tool_proposal_refs == ("tprop_12345678",)
        assert checkpoint is not None
        serialized = checkpoint.to_checkpoint()
        assert serialized["tool_proposal_refs"] == ["tprop_12345678"]
        assert "arguments" not in serialized
        assert "action_digest" not in serialized

    asyncio.run(scenario())
