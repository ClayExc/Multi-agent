from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest
from flowpilot_agent_runtime import (
    AgentProfile,
    AgentRunRequest,
    ProviderSelection,
    RuntimeBudget,
    SandboxAdapter,
)
from flowpilot_context import ContextBuilder, ContextBuildRequest, ContextPolicy
from flowpilot_domain import DataClassification, TaskCommand
from flowpilot_graph import (
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_model_gateway import (
    DeterministicModelGateway,
    ProviderRoute,
    SandboxProvider,
)

SANDBOX_ROUTE = ProviderRoute(
    provider="sandbox",
    model="sandbox-fake",
    maximum_classification=DataClassification.RESTRICTED,
)


@pytest.fixture
def sandbox_policy() -> ContextPolicy:
    return ContextPolicy(
        context_policy_version="ctx-policy-v1",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("sandbox",),
        token_budget=4096,
    )


@pytest.fixture
def sandbox_provider(
    fixed_clock: Callable[[], datetime],
) -> SandboxProvider:
    return SandboxProvider(name="sandbox", model="sandbox-fake", clock=fixed_clock)


@pytest.fixture
def sandbox_gateway(
    sandbox_provider: SandboxProvider,
) -> DeterministicModelGateway:
    return DeterministicModelGateway(
        routes=(SANDBOX_ROUTE,),
        providers={"sandbox": sandbox_provider},
    )


@pytest.fixture
def sandbox_adapter(
    sandbox_gateway: DeterministicModelGateway,
    fixed_clock: Callable[[], datetime],
) -> SandboxAdapter:
    return SandboxAdapter(sandbox_gateway, clock=fixed_clock)


@pytest.fixture
def build_request_factory(
    command_factory: Callable[..., TaskCommand],
    fixed_clock: Callable[[], datetime],
    sandbox_policy: ContextPolicy,
    runtime_budget: RuntimeBudget,
) -> Callable[..., AgentRunRequest]:
    def factory(
        *,
        agent: AgentProfile,
        command: TaskCommand | None = None,
        provider: ProviderSelection | None = None,
        budget: RuntimeBudget | None = None,
        request_id: str = "arq_12345678",
    ) -> AgentRunRequest:
        effective_command = command or command_factory()
        context = ContextBuilder(clock=fixed_clock).build(
            ContextBuildRequest(
                context_id="ctx_12345678",
                task_id=effective_command.task_id,
                agent_id=agent.id,
                purpose=effective_command.security_context.purpose,
                security_context=effective_command.security_context,
                task_state={"status": "RUNNING"},
                task_state_ref=f"task://{effective_command.task_id}/v1",
                system_policy_ref="policy://runtime/v1",
                policy=sandbox_policy,
            )
        )
        return AgentRunRequest(
            request_id=request_id,
            task_id=effective_command.task_id,
            tenant_id=effective_command.tenant_id,
            trace_id="0123456789abcdef0123456789abcdef",
            run_id="run_12345678",
            agent=agent,
            context=context,
            security_context=effective_command.security_context,
            provider_selection=provider
            or ProviderSelection(
                provider="sandbox",
                model="sandbox-fake",
                data_policy_id="data-policy-v1",
                routing_reason_code="TEST_PROVIDER_SELECTION",
            ),
            budget=budget or runtime_budget,
            session_ref=None,
            issued_at=fixed_clock(),
        )

    return factory


@pytest.fixture
def sandbox_kernel_factory(
    fixed_clock: Callable[[], datetime],
    sandbox_policy: ContextPolicy,
    runtime_budget: RuntimeBudget,
    agent_profile: AgentProfile,
) -> Callable[
    ..., tuple[RuntimeGraphKernel, InMemoryLeaseStore, InMemoryCheckpointStore]
]:
    def factory(
        runtime: SandboxAdapter,
        *,
        agent: AgentProfile | None = None,
        maximum_attempts: int = 2,
        graph_version: str = "graph-v1",
    ) -> tuple[RuntimeGraphKernel, InMemoryLeaseStore, InMemoryCheckpointStore]:
        leases = InMemoryLeaseStore(clock=fixed_clock)
        checkpoints = InMemoryCheckpointStore(leases=leases)
        kernel = RuntimeGraphKernel(
            config=RuntimeGraphConfig(
                graph_version=graph_version,
                context_policy=sandbox_policy,
                agent=agent or agent_profile,
                provider=ProviderSelection(
                    provider="sandbox",
                    model="sandbox-fake",
                    data_policy_id="data-policy-v1",
                    routing_reason_code="TEST_PROVIDER_SELECTION",
                ),
                budget=runtime_budget,
                maximum_attempts=maximum_attempts,
            ),
            context_builder=ContextBuilder(clock=fixed_clock),
            runtime=runtime,
            checkpoints=checkpoints,
            clock=fixed_clock,
        )
        return kernel, leases, checkpoints

    return factory
