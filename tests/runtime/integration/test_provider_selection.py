"""FP-AGT-003: 一个节点只使用一个 Provider（Trace Provider 断言）。

The graph kernel records one provider-selection trace entry per runtime node
run.  These tests drive the real chain (kernel -> SandboxAdapter ->
ModelGatewayPort -> SandboxProvider) and assert single-provider selection,
allowlist routing and classification-ceiling routing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from flowpilot_agent_runtime import RunStatus, SandboxAdapter
from flowpilot_domain import DataClassification, TaskCommand
from flowpilot_graph import (
    GraphNode,
    GraphRunOutcome,
    GraphStatus,
    InMemoryLeaseStore,
    RuntimeGraphKernel,
)
from flowpilot_model_gateway import (
    DeterministicModelGateway,
    ProviderRoute,
    SandboxProvider,
)


async def _run_kernel_once(
    kernel: RuntimeGraphKernel,
    leases: InMemoryLeaseStore,
    command: TaskCommand,
    *,
    tenant_id: str,
    task_id: str,
) -> tuple[object, GraphRunOutcome]:
    lease = await leases.acquire(tenant_id, task_id, run_id="run_12345678")
    prepared = await kernel.prepare(command, execution_ref="exec_ref_1", lease=lease)
    assert prepared.request is not None
    result = await kernel.invoke(prepared.request)
    outcome = await kernel.finalize(prepared.state, result, lease=lease)
    return result, outcome


def test_single_provider_used_per_runtime_node(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    sandbox_adapter: SandboxAdapter,
) -> None:
    command = command_factory()
    kernel, leases, _ = sandbox_kernel_factory(sandbox_adapter)

    result, outcome = asyncio.run(
        _run_kernel_once(
            kernel,
            leases,
            command,
            tenant_id=command.tenant_id,
            task_id=command.task_id,
        )
    )

    assert result.status is RunStatus.COMPLETED
    assert result.provider_name == "sandbox"
    assert result.provider_model == "sandbox-fake"
    assert outcome.state.status is GraphStatus.COMPLETED
    # Trace assertion: exactly one provider-selection record for the single
    # runtime node, always the same provider.
    selections = kernel.provider_selections
    assert len(selections) == 1
    assert selections[0].node is GraphNode.RUN_AGENT
    assert selections[0].provider == "sandbox"
    assert selections[0].model == "sandbox-fake"
    assert selections[0].trace_id == result.trace_id
    assert selections[0].provider_run_ref == result.provider_run_ref
    assert len({selection.provider for selection in selections}) == 1


def test_provider_allowlist_routing_is_respected(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    fixed_clock: Callable,
) -> None:
    # No approved route exists for the sandbox provider: the gateway denies
    # the route and the adapter maps it to a stable final runtime error.
    gateway = DeterministicModelGateway(
        routes=(),
        providers={"sandbox": SandboxProvider(clock=fixed_clock)},
    )
    adapter = SandboxAdapter(gateway, clock=fixed_clock)
    command = command_factory()
    kernel, leases, _ = sandbox_kernel_factory(adapter)

    result, outcome = asyncio.run(
        _run_kernel_once(
            kernel,
            leases,
            command,
            tenant_id=command.tenant_id,
            task_id=command.task_id,
        )
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.code.value == "RUNTIME_INTERNAL"
    assert result.error.retryable is False
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_INTERNAL"
    assert len(gateway.calls) == 1
    assert len(adapter.calls) == 1
    assert len(kernel.provider_selections) == 1


def test_classification_ceiling_routing_is_respected(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    fixed_clock: Callable,
) -> None:
    # The request carries CONFIDENTIAL data (security ceiling); the only
    # route allows at most INTERNAL, so the gateway must deny routing.
    gateway = DeterministicModelGateway(
        routes=(
            ProviderRoute(
                provider="sandbox",
                model="sandbox-fake",
                maximum_classification=DataClassification.INTERNAL,
            ),
        ),
        providers={"sandbox": SandboxProvider(clock=fixed_clock)},
    )
    adapter = SandboxAdapter(gateway, clock=fixed_clock)
    command = command_factory()
    kernel, leases, _ = sandbox_kernel_factory(adapter)

    result, outcome = asyncio.run(
        _run_kernel_once(
            kernel,
            leases,
            command,
            tenant_id=command.tenant_id,
            task_id=command.task_id,
        )
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.detail_ref == "model_route_denied"
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_INTERNAL"
    assert len(gateway.calls) == 1
