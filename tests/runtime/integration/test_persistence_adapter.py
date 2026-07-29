from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

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
    GraphError,
    GraphErrorCode,
    GraphNode,
    GraphState,
    GraphStatus,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_persistence import (
    MemoryDatabase,
    MemoryDataUnitOfWorkFactory,
)
from flowpilot_worker import (
    InMemoryExecutionQueue,
    PersistenceCheckpointAdapter,
    PersistenceLeaseAdapter,
    PersistenceRuntimeConfig,
    RuntimeExecutionAdapter,
    RuntimeWorker,
)


class BrokenUnitOfWorkFactory:
    def __call__(self) -> None:
        raise RuntimeError("postgresql://user:secret@database/internal")


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


def _request_id(command_id: str, attempt: int) -> str:
    suffix = hashlib.sha256(
        f"{command_id}:{attempt}".encode()
    ).hexdigest()[:16]
    return f"arq_{suffix}"


def _graph(
    *,
    checkpoints: PersistenceCheckpointAdapter,
    runtime: FakeAgentRuntime,
    clock: Callable[[], datetime],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
) -> LangGraphRuntime:
    kernel = RuntimeGraphKernel(
        config=RuntimeGraphConfig(
            graph_version="graph-v1",
            context_policy=context_policy,
            agent=agent_profile,
            provider=provider_selection,
            budget=runtime_budget,
        ),
        context_builder=ContextBuilder(clock=clock),
        runtime=runtime,
        checkpoints=checkpoints,
        clock=clock,
    )
    return LangGraphRuntime(kernel)


def _state(command: TaskCommand, *, run_id: str, generation: int) -> GraphState:
    return GraphState(
        task_id=command.task_id,
        tenant_id=command.tenant_id,
        command_id=command.command_id,
        command_digest=command.command_digest,
        run_id=run_id,
        run_generation=generation,
        graph_version="graph-v1",
        status=GraphStatus.QUEUED,
        node=GraphNode.START,
        security_context_ref=command.security_context.context_ref,
        security_context_hash=command.security_context.context_hash,
        purpose=command.security_context.purpose,
    )


def test_persistence_adapters_drive_worker_and_restore_checkpoint(
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
        database = MemoryDatabase()
        database.seed_task(task_factory())
        unit_of_work = MemoryDataUnitOfWorkFactory(database)
        leases = PersistenceLeaseAdapter(unit_of_work, clock=fixed_clock)
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        runtime = FakeAgentRuntime(clock=fixed_clock)
        graph = _graph(
            checkpoints=checkpoints,
            runtime=runtime,
            clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        worker = RuntimeWorker(
            worker_id="worker-persistence",
            queue=queue,
            leases=leases,
            graph=graph,
            run_id_factory=lambda: "run_persistent_12345678",
        )

        result = await worker.run_once()
        restored = await checkpoints.load(
            command.tenant_id,
            command.task_id,
        )

        assert result.graph_outcome is not None
        assert result.graph_outcome.state.status is GraphStatus.COMPLETED
        assert restored == result.graph_outcome.state
        assert restored is not None
        assert restored.checkpoint_sequence == 3
        assert len(runtime.calls) == 1

    asyncio.run(scenario())


def test_checkpoint_cas_is_idempotent_and_rejects_stale_content(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        database = MemoryDatabase()
        database.seed_task(task_factory())
        unit_of_work = MemoryDataUnitOfWorkFactory(database)
        leases = PersistenceLeaseAdapter(unit_of_work, clock=fixed_clock)
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_cas_12345678",
        )
        state = _state(
            command,
            run_id=lease.run_id,
            generation=lease.run_generation,
        )

        first = await checkpoints.save(
            state,
            expected_sequence=0,
            lease=lease,
        )
        replay = await checkpoints.save(
            state,
            expected_sequence=0,
            lease=lease,
        )

        assert replay == first
        assert first.checkpoint_sequence == 1

        with pytest.raises(GraphError) as captured:
            await checkpoints.save(
                replace(state, command_digest="sha256:" + "f" * 64),
                expected_sequence=0,
                lease=lease,
            )

        assert captured.value.code is GraphErrorCode.CHECKPOINT_CONFLICT

    asyncio.run(scenario())


def test_task_projection_identity_mismatch_fails_closed(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        database = MemoryDatabase()
        mismatched = task_factory(tenant_id="tenant-b")
        database.state.tasks[
            (command.tenant_id, command.task_id)
        ] = mismatched
        unit_of_work = MemoryDataUnitOfWorkFactory(database)
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )

        with pytest.raises(GraphError) as captured:
            await checkpoints.load(command.tenant_id, command.task_id)

        assert captured.value.code is GraphErrorCode.STATE_INVALID
        assert "tenant-b" not in captured.value.safe_message

    asyncio.run(scenario())


def test_thread_rebinding_cannot_read_or_overwrite_checkpoint_history(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        database = MemoryDatabase()
        database.seed_task(task_factory(thread_id="thread_12345678"))
        unit_of_work = MemoryDataUnitOfWorkFactory(database)
        leases = PersistenceLeaseAdapter(unit_of_work, clock=fixed_clock)
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_thread_12345678",
        )
        state = _state(
            command,
            run_id=lease.run_id,
            generation=lease.run_generation,
        )
        await checkpoints.save(
            state,
            expected_sequence=0,
            lease=lease,
        )
        database.seed_task(task_factory(thread_id="thread_87654321"))

        assert await checkpoints.load(
            command.tenant_id,
            command.task_id,
        ) is None
        with pytest.raises(GraphError) as captured:
            await checkpoints.save(
                state,
                expected_sequence=0,
                lease=lease,
            )

        assert captured.value.code is GraphErrorCode.CHECKPOINT_CONFLICT

    asyncio.run(scenario())


def test_storage_exception_is_sanitized_and_retryable() -> None:
    checkpoints = PersistenceCheckpointAdapter(
        BrokenUnitOfWorkFactory(),  # type: ignore[arg-type]
    )

    with pytest.raises(GraphError) as captured:
        asyncio.run(checkpoints.load("tenant-a", "task_12345678"))

    assert captured.value.code is GraphErrorCode.CHECKPOINT_UNAVAILABLE
    assert captured.value.retryable is True
    assert "secret" not in captured.value.safe_message
    assert "postgresql" not in captured.value.safe_message


def test_expired_and_old_generation_leases_are_fenced(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        clock = MutableClock(fixed_clock())
        database = MemoryDatabase()
        database.seed_task(task_factory())
        unit_of_work = MemoryDataUnitOfWorkFactory(database)
        config = PersistenceRuntimeConfig(lease_ttl=timedelta(seconds=30))
        leases = PersistenceLeaseAdapter(
            unit_of_work,
            config=config,
            clock=clock,
        )
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=clock,
        )
        old = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_old_12345678",
        )
        clock.advance(timedelta(seconds=31))

        with pytest.raises(GraphError) as expired:
            await leases.assert_valid(old)
        assert expired.value.code is GraphErrorCode.LEASE_LOST

        current = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_current_12345678",
        )
        assert current.run_generation == 2

        with pytest.raises(GraphError) as stale:
            await checkpoints.save(
                _state(
                    command,
                    run_id=old.run_id,
                    generation=old.run_generation,
                ),
                expected_sequence=0,
                lease=old,
            )
        assert stale.value.code is GraphErrorCode.LEASE_LOST

    asyncio.run(scenario())


def test_worker_restart_resumes_from_persistent_checkpoint(
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
        database = MemoryDatabase()
        database.seed_task(task_factory())
        unit_of_work = MemoryDataUnitOfWorkFactory(database)
        leases = PersistenceLeaseAdapter(unit_of_work, clock=fixed_clock)
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        runtime = FakeAgentRuntime(clock=fixed_clock)
        runtime.script(
            _request_id(command.command_id, 1),
            (FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),),
        )
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        first_graph = _graph(
            checkpoints=checkpoints,
            runtime=runtime,
            clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        first_worker = RuntimeWorker(
            worker_id="worker-before-restart",
            queue=queue,
            leases=leases,
            graph=first_graph,
            run_id_factory=lambda: "run_before_restart_12345678",
        )
        first = await first_worker.run_once()

        restarted_checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        restarted_leases = PersistenceLeaseAdapter(
            unit_of_work,
            clock=fixed_clock,
        )
        restarted_graph = _graph(
            checkpoints=restarted_checkpoints,
            runtime=runtime,
            clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        restarted_worker = RuntimeWorker(
            worker_id="worker-after-restart",
            queue=queue,
            leases=restarted_leases,
            graph=restarted_graph,
            run_id_factory=lambda: "run_after_restart_12345678",
        )
        second = await restarted_worker.run_once()
        restored = await restarted_checkpoints.load(
            command.tenant_id,
            command.task_id,
        )

        assert first.graph_outcome is not None
        assert first.graph_outcome.should_retry is True
        assert second.graph_outcome is not None
        assert second.graph_outcome.state.status is GraphStatus.COMPLETED
        assert restored == second.graph_outcome.state
        assert restored is not None
        assert restored.attempt_count == 2
        assert len(runtime.calls) == 2
        assert queue.acknowledged_count == 1

    asyncio.run(scenario())
