"""FP-AGT-001: 知识/数据/规划 Agent 职责与工具隔离（工具权限矩阵）。

The permission matrix is asserted two ways: (1) each agent profile carries
exactly its declared tool set and the sets are disjoint (responsibility
isolation); (2) the sandbox runtime path enforces the matrix on every wire
tool proposal -- an in-scope proposal passes, an out-of-scope proposal is
rejected with TOOL_SCOPE_VIOLATION.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from flowpilot_agent_runtime import (
    AgentMode,
    AgentProfile,
    AgentRunRequest,
    AllowedTool,
    OutputSchemaRef,
    RunStatus,
    RuntimeErrorCode,
    SandboxAdapter,
    ToolOperation,
)
from flowpilot_domain import DataClassification
from flowpilot_model_gateway import (
    DeterministicModelGateway,
    ProviderRoute,
    SandboxProvider,
    SandboxScenario,
    WireToolOperation,
    sandbox_proposal,
)

_RESTRICTED_ROUTE = ProviderRoute(
    provider="sandbox",
    model="sandbox-fake",
    maximum_classification=DataClassification.RESTRICTED,
)

_AGENT_MATRIX: dict[str, tuple[tuple[str, ToolOperation], ...]] = {
    "knowledge-agent": (
        ("knowledge.search.v1", ToolOperation.READ),
        ("knowledge.read.v1", ToolOperation.READ),
    ),
    "planning-agent": (
        ("itsm.ticket.create.v1", ToolOperation.PROPOSE_WRITE),
        ("itsm.ticket.update.v1", ToolOperation.PROPOSE_WRITE),
    ),
    "data-agent": (
        ("data.query.v1", ToolOperation.READ),
        ("data.export.v1", ToolOperation.PROPOSE_WRITE),
    ),
}


def _profile_for(agent_id: str) -> AgentProfile:
    allowed = tuple(
        AllowedTool(
            name=name,
            schema_hash="sha256:" + "b" * 64,
            operation=operation,
        )
        for name, operation in _AGENT_MATRIX[agent_id]
    )
    return AgentProfile(
        id=agent_id,
        version="1.0.0",
        prompt_version="prompt-v1",
        mode=AgentMode.BOUNDED_AGENT_LOOP,
        output_schema=OutputSchemaRef(
            id=f"schema://{agent_id}/v1",
            hash="sha256:" + "a" * 64,
        ),
        allowed_tools=allowed,
        maximum_handoffs=1,
    )


def test_tool_permission_matrix_is_exact_and_disjoint() -> None:
    matrices = {
        agent_id: {
            (tool.name, tool.operation) for tool in _profile_for(agent_id).allowed_tools
        }
        for agent_id in _AGENT_MATRIX
    }
    for agent_id, expected in _AGENT_MATRIX.items():
        assert matrices[agent_id] == set(expected)
    # Responsibility isolation: no tool is shared between agents.
    for agent_id, allowed in matrices.items():
        others = {
            tool
            for other_id, other_allowed in matrices.items()
            if other_id != agent_id
            for tool in other_allowed
        }
        assert allowed.isdisjoint(others)


def test_sandbox_path_enforces_matrix_for_every_agent(
    build_request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable,
) -> None:
    for agent_id in _AGENT_MATRIX:
        agent = _profile_for(agent_id)
        in_scope_name, in_scope_operation = _AGENT_MATRIX[agent_id][0]
        out_of_scope_name = next(
            name
            for other_id, tools in _AGENT_MATRIX.items()
            if other_id != agent_id
            for name, _operation in tools
        )
        allowed_proposal = sandbox_proposal(
            proposal_id=f"tprop_in_{agent_id}",
            name=in_scope_name,
            operation=(
                WireToolOperation.READ
                if in_scope_operation is ToolOperation.READ
                else WireToolOperation.PROPOSE_WRITE
            ),
            arguments={"query": "vpn"},
            purpose="resolve_vpn_incident",
        )
        provider = SandboxProvider(
            name="sandbox",
            default=SandboxScenario(tool_proposals=(allowed_proposal,)),
            clock=fixed_clock,
        )
        gateway = DeterministicModelGateway(
            routes=(_RESTRICTED_ROUTE,),
            providers={"sandbox": provider},
        )
        adapter = SandboxAdapter(gateway, clock=fixed_clock)

        passed = asyncio.run(adapter.run(build_request_factory(agent=agent)))
        assert passed.status is RunStatus.COMPLETED
        assert passed.tool_proposals[0].tool == in_scope_name

        # Same request, out-of-scope proposal: rejected by the runtime port.
        denied_proposal = sandbox_proposal(
            proposal_id=f"tprop_out_{agent_id}",
            name=out_of_scope_name,
            operation=WireToolOperation.PROPOSE_WRITE,
            arguments={"summary": "VPN"},
            purpose="resolve_vpn_incident",
        )
        denied_provider = SandboxProvider(
            name="sandbox",
            default=SandboxScenario(tool_proposals=(denied_proposal,)),
            clock=fixed_clock,
        )
        denied_gateway = DeterministicModelGateway(
            routes=(_RESTRICTED_ROUTE,),
            providers={"sandbox": denied_provider},
        )
        denied_adapter = SandboxAdapter(denied_gateway, clock=fixed_clock)

        rejected = asyncio.run(denied_adapter.run(build_request_factory(agent=agent)))
        assert rejected.status is RunStatus.FAILED_FINAL
        assert rejected.error is not None
        assert rejected.error.code is RuntimeErrorCode.TOOL_SCOPE_VIOLATION
        assert rejected.structured_output is None
        assert rejected.tool_proposals == ()


def test_tool_scope_rejects_credential_shaped_arguments(
    build_request_factory: Callable[..., AgentRunRequest],
    fixed_clock: Callable,
) -> None:
    agent = _profile_for("knowledge-agent")
    proposal = sandbox_proposal(
        proposal_id="tprop_cred_1",
        name="knowledge.search.v1",
        operation=WireToolOperation.READ,
        arguments={"query": "vpn", "api_key": "secret"},
        purpose="resolve_vpn_incident",
    )
    provider = SandboxProvider(
        name="sandbox",
        default=SandboxScenario(tool_proposals=(proposal,)),
        clock=fixed_clock,
    )
    gateway = DeterministicModelGateway(
        routes=(_RESTRICTED_ROUTE,),
        providers={"sandbox": provider},
    )
    adapter = SandboxAdapter(gateway, clock=fixed_clock)

    result = asyncio.run(adapter.run(build_request_factory(agent=agent)))

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.TOOL_SCOPE_VIOLATION
