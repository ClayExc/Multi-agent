from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import cast

import pytest
from flowpilot_agent_runtime import (
    AgentProfile,
    FakeAgentRuntime,
    FakeOutcome,
    FakeScenario,
    ProviderSelection,
    RuntimeBudget,
)
from flowpilot_context import ContextBuilder, ContextPolicy
from flowpilot_domain import Task, TaskCommand
from flowpilot_graph import (
    CheckpointPort,
    GraphError,
    GraphErrorCode,
    GraphExecutionPort,
    GraphStatus,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_persistence import (
    CoordinationRebuilder,
    CoordinationSignal,
    MemoryDataUnitOfWorkFactory,
    MemoryRedisClient,
    OutboxEvent,
    RedisCoordinationAdapter,
)
from flowpilot_worker import (
    DurableGraphFactory,
    InMemoryExecutionQueue,
    PersistenceCheckpointAdapter,
    PersistenceExecutionGuard,
    RuntimeExecutionAdapter,
    TrustedTenantInventory,
    build_durable_runtime,
)

from tests.runtime.identity_helpers import MutableSecurityContextValidator


def _request_id(command_id: str, attempt: int) -> str:
    suffix = hashlib.sha256(f"{command_id}:{attempt}".encode()).hexdigest()[:16]
    return f"arq_{suffix}"


def _runnable(task: Task) -> Task:
    value = task.to_mapping()
    value.update(
        {
            "status": "RUNNABLE",
            "active_run_id": None,
            "latest_checkpoint_id": None,
            "waiting_on": None,
            "result_ref": None,
            "error": None,
            "completed_at": None,
        }
    )
    return Task.from_mapping(value)


def _graph_factory(
    *,
    runtime: FakeAgentRuntime,
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> tuple[DurableGraphFactory, list[object]]:
    observed_checkpointers: list[object] = []

    def factory(
        *,
        checkpoints: CheckpointPort,
        control_checkpointer: object,
    ) -> GraphExecutionPort:
        observed_checkpointers.append(control_checkpointer)
        kernel = RuntimeGraphKernel(
            config=RuntimeGraphConfig(
                graph_version="graph-v1",
                context_policy=context_policy,
                agent=agent_profile,
                provider=provider_selection,
                budget=runtime_budget,
            ),
            context_builder=ContextBuilder(clock=fixed_clock),
            runtime=runtime,
            checkpoints=checkpoints,
            clock=fixed_clock,
        )
        return LangGraphRuntime(kernel)

    return cast(DurableGraphFactory, factory), observed_checkpointers


def _outbox_event(command: TaskCommand, now: datetime) -> OutboxEvent:
    return OutboxEvent(
        event_id="evt_durable_runtime_12345678",
        tenant_id=command.tenant_id,
        aggregate_type="task",
        aggregate_id=command.task_id,
        sequence=1,
        event_type="task.status.changed.v1",
        payload={"from": "RECEIVED", "to": "RUNNABLE"},
        occurred_at=now,
        available_at=now,
    )


def test_runtime_rebuilds_lost_coordination_before_dequeue(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> None:
    async def scenario() -> None:
        command = command_factory()
        unit_of_work = MemoryDataUnitOfWorkFactory()
        task = _runnable(task_factory())
        unit_of_work.database.seed_task(task)
        async with unit_of_work() as data:
            await data.outbox.append(_outbox_event(command, fixed_clock()))
            await data.commit()

        redis = MemoryRedisClient()
        coordination = RedisCoordinationAdapter(redis)
        await coordination.signal(
            CoordinationSignal(
                tenant_id=command.tenant_id,
                task_id="task_stale_runtime_12345678",
                run_generation=99,
                available_at=fixed_clock(),
            )
        )
        await coordination.clear()
        graph_factory, _ = _graph_factory(
            runtime=FakeAgentRuntime(clock=fixed_clock),
            fixed_clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        runtime = build_durable_runtime(
            worker_id="worker_rebuild_12345678",
            queue=InMemoryExecutionQueue(),
            unit_of_work=unit_of_work,
            coordination_rebuilder=CoordinationRebuilder(
                unit_of_work,
                coordination,
            ),
            tenants=TrustedTenantInventory((command.tenant_id,)),
            graph_factory=graph_factory,
            security_contexts=MutableSecurityContextValidator(),
            control_checkpointer=object(),
            clock=fixed_clock,
        )

        result = await runtime.run_once()

        assert result.idle is True
        assert runtime.rebuilt_signal_count == 1
        assert set(redis.values) == {
            coordination.key(command.tenant_id, command.task_id)
        }

    asyncio.run(scenario())


def test_new_runtime_generation_resumes_cas_and_terminal_does_not_rerun(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> None:
    async def scenario() -> None:
        command = command_factory()
        unit_of_work = MemoryDataUnitOfWorkFactory()
        unit_of_work.database.seed_task(task_factory())
        runtime_port = FakeAgentRuntime(clock=fixed_clock)
        runtime_port.script(
            _request_id(command.command_id, 1),
            (FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),),
        )
        redis = MemoryRedisClient()
        rebuilder = CoordinationRebuilder(
            unit_of_work,
            RedisCoordinationAdapter(redis),
        )
        tenants = TrustedTenantInventory((command.tenant_id,))
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)

        first_factory, first_observed = _graph_factory(
            runtime=runtime_port,
            fixed_clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        first_control = object()
        before_restart = build_durable_runtime(
            worker_id="worker_before_restart_12345678",
            queue=queue,
            unit_of_work=unit_of_work,
            coordination_rebuilder=rebuilder,
            tenants=tenants,
            graph_factory=first_factory,
            security_contexts=MutableSecurityContextValidator(),
            control_checkpointer=first_control,
            clock=fixed_clock,
            run_id_factory=lambda: "run_before_restart_12345678",
        )
        first = await before_restart.run_once()
        assert first.graph_outcome is not None
        assert first.graph_outcome.should_retry is True
        first_sequence = first.graph_outcome.state.checkpoint_sequence

        second_factory, second_observed = _graph_factory(
            runtime=runtime_port,
            fixed_clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        second_control = object()
        after_restart = build_durable_runtime(
            worker_id="worker_after_restart_12345678",
            queue=queue,
            unit_of_work=unit_of_work,
            coordination_rebuilder=rebuilder,
            tenants=tenants,
            graph_factory=second_factory,
            security_contexts=MutableSecurityContextValidator(),
            control_checkpointer=second_control,
            clock=fixed_clock,
            run_id_factory=lambda: "run_after_restart_12345678",
        )
        second = await after_restart.run_once()
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        completed = await checkpoints.load(command.tenant_id, command.task_id)

        assert first_observed == [first_control]
        assert second_observed == [second_control]
        assert second.graph_outcome is not None
        assert second.graph_outcome.state.status is GraphStatus.COMPLETED
        assert completed is not None
        assert completed.run_generation == 2
        assert completed.checkpoint_sequence > first_sequence
        completed_sequence = completed.checkpoint_sequence
        assert len(runtime_port.calls) == 2

        duplicate_queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(duplicate_queue).submit(command)
        duplicate_factory, _ = _graph_factory(
            runtime=runtime_port,
            fixed_clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        duplicate_runtime = build_durable_runtime(
            worker_id="worker_terminal_replay_12345678",
            queue=duplicate_queue,
            unit_of_work=unit_of_work,
            coordination_rebuilder=rebuilder,
            tenants=tenants,
            graph_factory=duplicate_factory,
            security_contexts=MutableSecurityContextValidator(),
            control_checkpointer=object(),
            clock=fixed_clock,
            run_id_factory=lambda: "run_terminal_replay_12345678",
        )
        replay = await duplicate_runtime.run_once()
        after_replay = await checkpoints.load(command.tenant_id, command.task_id)

        assert replay.graph_outcome is not None
        assert replay.graph_outcome.state.status is GraphStatus.COMPLETED
        assert len(runtime_port.calls) == 2
        assert after_replay is not None
        assert after_replay.checkpoint_sequence == completed_sequence

    asyncio.run(scenario())


def test_untrusted_command_tenant_is_rejected_before_lease(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> None:
    async def scenario() -> None:
        command = command_factory()
        unit_of_work = MemoryDataUnitOfWorkFactory()
        unit_of_work.database.seed_task(task_factory())
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        graph_factory, _ = _graph_factory(
            runtime=FakeAgentRuntime(clock=fixed_clock),
            fixed_clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        runtime = build_durable_runtime(
            worker_id="worker_untrusted_tenant_12345678",
            queue=queue,
            unit_of_work=unit_of_work,
            coordination_rebuilder=CoordinationRebuilder(
                unit_of_work,
                RedisCoordinationAdapter(MemoryRedisClient()),
            ),
            tenants=TrustedTenantInventory(("tenant-b",)),
            graph_factory=graph_factory,
            security_contexts=MutableSecurityContextValidator(),
            control_checkpointer=object(),
            clock=fixed_clock,
        )

        with pytest.raises(GraphError) as captured:
            await runtime.run_once()

        assert captured.value.code is GraphErrorCode.SECURITY_BINDING_MISMATCH
        assert queue.acknowledged_count == 1
        assert unit_of_work.database.state.leases == {}

    asyncio.run(scenario())


def test_command_must_match_durable_task_security_binding(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        task_value = task_factory().to_mapping()
        task_value["security_context"]["context_hash"] = "sha256:" + "f" * 64
        unit_of_work = MemoryDataUnitOfWorkFactory()
        unit_of_work.database.seed_task(Task.from_mapping(task_value))
        guard = PersistenceExecutionGuard(
            unit_of_work,
            TrustedTenantInventory((command.tenant_id,)),
        )

        with pytest.raises(GraphError) as captured:
            await guard.validate(command)

        assert captured.value.code is GraphErrorCode.SECURITY_BINDING_MISMATCH
        assert unit_of_work.database.state.leases == {}

    asyncio.run(scenario())


def test_control_checkpointer_must_be_explicitly_configured(
    fixed_clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> None:
    unit_of_work = MemoryDataUnitOfWorkFactory()
    graph_factory, _ = _graph_factory(
        runtime=FakeAgentRuntime(clock=fixed_clock),
        fixed_clock=fixed_clock,
        context_policy=context_policy,
        agent_profile=agent_profile,
        provider_selection=provider_selection,
        runtime_budget=runtime_budget,
    )

    with pytest.raises(ValueError, match="explicitly configured"):
        build_durable_runtime(
            worker_id="worker_missing_control_12345678",
            queue=InMemoryExecutionQueue(),
            unit_of_work=unit_of_work,
            coordination_rebuilder=CoordinationRebuilder(
                unit_of_work,
                RedisCoordinationAdapter(MemoryRedisClient()),
            ),
            tenants=TrustedTenantInventory(("tenant-a",)),
            graph_factory=graph_factory,
            security_contexts=MutableSecurityContextValidator(),
            control_checkpointer=None,  # type: ignore[arg-type]
            clock=fixed_clock,
        )
