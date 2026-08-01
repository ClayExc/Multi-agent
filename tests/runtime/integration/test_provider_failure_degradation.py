"""FP-OPS-003（Provider 故障降级部分）: Provider 不可用 → 唯一 retryable 降级。

The sandbox provider is scripted to fail exactly like a real provider
outage.  The chain (kernel -> SandboxAdapter -> ModelGatewayPort ->
SandboxProvider) must: (1) map the outage to the unique retryable runtime
error, (2) let the graph retry and recover when the provider returns, and
(3) never leak a raw provider exception to the caller.  Non-retryable
failures must not be retried.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable

from flowpilot_agent_runtime import (
    RunStatus,
    RuntimeErrorCode,
    SandboxAdapter,
)
from flowpilot_domain import DataClassification, TaskCommand
from flowpilot_graph import (
    GraphStatus,
    InMemoryLeaseStore,
    RuntimeGraphKernel,
)
from flowpilot_model_gateway import (
    DeterministicModelGateway,
    ProviderRoute,
    ProviderWireError,
    ProviderWireErrorCode,
    SandboxProvider,
    SandboxScenario,
)

_UNAVAILABLE = ProviderWireError(
    ProviderWireErrorCode.PROVIDER_UNAVAILABLE,
    "sandbox provider outage",
    retryable=True,
)

_SANDBOX_ROUTE = ProviderRoute(
    provider="sandbox",
    model="sandbox-fake",
    maximum_classification=DataClassification.RESTRICTED,
)


def _kernel_request_id(command_id: str, attempt: int) -> str:
    """Replicate the kernel's stable request id derivation (deterministic)."""
    suffix = hashlib.sha256(f"{command_id}:{attempt}".encode()).hexdigest()[:16]
    return f"arq_{suffix}"


def _sandbox_runtime(
    provider: SandboxProvider,
    fixed_clock: Callable,
) -> tuple[SandboxAdapter, DeterministicModelGateway]:
    gateway = DeterministicModelGateway(
        routes=(_SANDBOX_ROUTE,),
        providers={"sandbox": provider},
    )
    return SandboxAdapter(gateway, clock=fixed_clock), gateway


async def _run_attempt(
    kernel: RuntimeGraphKernel,
    leases: InMemoryLeaseStore,
    command: TaskCommand,
    *,
    execution_ref: str,
) -> tuple[object, object]:
    lease = await leases.acquire(
        command.tenant_id, command.task_id, run_id="run_12345678"
    )
    prepared = await kernel.prepare(command, execution_ref=execution_ref, lease=lease)
    assert prepared.request is not None
    result = await kernel.invoke(prepared.request)
    outcome = await kernel.finalize(prepared.state, result, lease=lease)
    return result, outcome


def test_provider_outage_degrades_to_unique_retryable_then_recovers(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    fixed_clock: Callable,
) -> None:
    command = command_factory()
    provider = SandboxProvider(name="sandbox", clock=fixed_clock)
    # Attempt 1 fails; attempt 2 hits the healthy default.
    provider.script(
        _kernel_request_id(command.command_id, attempt=1),
        failure=_UNAVAILABLE,
    )
    adapter, gateway = _sandbox_runtime(provider, fixed_clock)
    kernel, leases, checkpoints = sandbox_kernel_factory(adapter, maximum_attempts=2)

    first, first_outcome = asyncio.run(
        _run_attempt(kernel, leases, command, execution_ref="exec_ref_1")
    )
    second, second_outcome = asyncio.run(
        _run_attempt(kernel, leases, command, execution_ref="exec_ref_2")
    )

    assert first.status is RunStatus.FAILED_RETRYABLE
    assert first.structured_output is None
    assert first.error is not None
    assert first.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert first.error.retryable is True
    assert first_outcome.state.status is GraphStatus.RETRY_PENDING
    assert first_outcome.should_retry is True
    assert first_outcome.state.failure_code == "RUNTIME_PROVIDER_UNAVAILABLE"

    assert second.status is RunStatus.COMPLETED
    assert second_outcome.state.status is GraphStatus.COMPLETED
    assert second_outcome.should_retry is False
    assert len(adapter.calls) == 2
    assert len(gateway.calls) == 2
    # Retry boundary left a deterministic trace record per attempt, all on
    # the same provider.
    selections = kernel.provider_selections
    assert len(selections) == 2
    assert len({selection.provider for selection in selections}) == 1
    assert all(selection.provider == "sandbox" for selection in selections)
    # Checkpoint history carries the retryable failure code.
    assert any(
        state.status is GraphStatus.RETRY_PENDING
        and state.failure_code == "RUNTIME_PROVIDER_UNAVAILABLE"
        for state in checkpoints.write_history
    )


def test_provider_outage_never_leaks_as_raw_exception(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    fixed_clock: Callable,
) -> None:
    command = command_factory()
    provider = SandboxProvider(
        name="sandbox",
        default=SandboxScenario(failure=_UNAVAILABLE),
        clock=fixed_clock,
    )
    adapter, _ = _sandbox_runtime(provider, fixed_clock)
    kernel, leases, _ = sandbox_kernel_factory(adapter, maximum_attempts=1)

    result, outcome = asyncio.run(
        _run_attempt(kernel, leases, command, execution_ref="exec_ref_1")
    )

    # adapter.run must return a failure result, never raise.  With a single
    # maximum attempt the retryable outage immediately exhausts the budget.
    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error is not None
    assert result.error.code is RuntimeErrorCode.PROVIDER_UNAVAILABLE
    assert outcome.state.status is GraphStatus.FAILED
    assert outcome.state.failure_code == "RUNTIME_PROVIDER_UNAVAILABLE"


def test_retries_exhaust_after_maximum_attempts(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    fixed_clock: Callable,
) -> None:
    command = command_factory()
    provider = SandboxProvider(
        name="sandbox",
        default=SandboxScenario(failure=_UNAVAILABLE),
        clock=fixed_clock,
    )
    adapter, gateway = _sandbox_runtime(provider, fixed_clock)
    kernel, leases, _ = sandbox_kernel_factory(adapter, maximum_attempts=2)

    first, first_outcome = asyncio.run(
        _run_attempt(kernel, leases, command, execution_ref="exec_ref_1")
    )
    second, second_outcome = asyncio.run(
        _run_attempt(kernel, leases, command, execution_ref="exec_ref_2")
    )

    assert first_outcome.state.status is GraphStatus.RETRY_PENDING
    assert second.status is RunStatus.FAILED_RETRYABLE
    assert second_outcome.state.status is GraphStatus.FAILED
    assert second_outcome.state.failure_code == "RUNTIME_PROVIDER_UNAVAILABLE"
    assert len(adapter.calls) == 2
    assert len(gateway.calls) == 2
    assert len(kernel.provider_selections) == 2


def test_non_retryable_route_failure_is_not_retried(
    command_factory: Callable[..., TaskCommand],
    sandbox_kernel_factory: Callable[..., tuple],
    fixed_clock: Callable,
) -> None:
    command = command_factory()
    # No approved route: a final routing failure, never retried.
    gateway = DeterministicModelGateway(
        routes=(),
        providers={"sandbox": SandboxProvider(clock=fixed_clock)},
    )
    adapter = SandboxAdapter(gateway, clock=fixed_clock)
    kernel, leases, _ = sandbox_kernel_factory(adapter, maximum_attempts=2)

    result, outcome = asyncio.run(
        _run_attempt(kernel, leases, command, execution_ref="exec_ref_1")
    )

    assert result.status is RunStatus.FAILED_FINAL
    assert result.error is not None
    assert result.error.retryable is False
    assert outcome.state.status is GraphStatus.FAILED
    assert len(adapter.calls) == 1
    assert len(gateway.calls) == 1
