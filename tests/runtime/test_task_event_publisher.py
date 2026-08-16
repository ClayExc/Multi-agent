"""Worker publishes task lifecycle events into the transactional outbox.

RUN_ID: run_g2_task_event_publisher_001

Evidence scope (tests/runtime/test_task_event_publisher.py):
- full lifecycle (intake -> running -> completed) emits
  task.created.v1 / task.status.changed.v1 / task.completed.v1 with
  contiguous per-task sequences inside the worker DataUnitOfWork
- failed runs emit task.failed.v1; user-input interrupts emit
  task.input.required.v1
- transactional outbox: a fault before commit rolls the events back
- replay idempotency: re-saving the same checkpoint emits no duplicate
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# The worker package imports its VPN graph which needs the tool-contracts
# source tree; the platform conftest supplies it in the full suite.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _source in (
    REPOSITORY_ROOT / "packages" / "tool-contracts" / "src",
    REPOSITORY_ROOT / "packages" / "policy" / "src",
    REPOSITORY_ROOT / "packages" / "security" / "src",
):
    if str(_source) not in sys.path:
        sys.path.insert(0, str(_source))

import pytest  # noqa: E402
from flowpilot_agent_runtime import (  # noqa: E402
    AgentProfile,
    FakeAgentRuntime,
    FakeOutcome,
    FakeScenario,
    ProviderSelection,
    RuntimeBudget,
)
from flowpilot_context import ContextBuilder, ContextPolicy  # noqa: E402
from flowpilot_domain import Task, TaskCommand  # noqa: E402
from flowpilot_graph import (  # noqa: E402
    GraphError,
    GraphErrorCode,
    GraphNode,
    GraphState,
    GraphStatus,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime  # noqa: E402
from flowpilot_persistence import (  # noqa: E402
    MemoryDatabase,
    MemoryDataUnitOfWorkFactory,
    OutboxEvent,
)
from flowpilot_worker import (  # noqa: E402
    InMemoryExecutionQueue,
    PersistenceCheckpointAdapter,
    PersistenceLeaseAdapter,
    RuntimeExecutionAdapter,
    RuntimeWorker,
    TaskEventPublisher,
)

from tests.runtime.identity_helpers import (  # noqa: E402
    MutableSecurityContextValidator,
)


class FaultyUnitOfWork:
    """Proxy that fails the next commit once (crash before commit)."""

    def __init__(self, inner: object, *, fail_next_commit: bool) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_fail_next_commit", fail_next_commit)

    def __getattr__(self, name: str) -> object:
        return getattr(object.__getattribute__(self, "_inner"), name)

    async def __aenter__(self) -> FaultyUnitOfWork:
        await object.__getattribute__(self, "_inner").__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await object.__getattribute__(self, "_inner").__aexit__(*args)

    async def commit(self) -> None:
        if object.__getattribute__(self, "_fail_next_commit"):
            object.__setattr__(self, "_fail_next_commit", False)
            raise RuntimeError("fault injection: checkpoint commit")
        await object.__getattribute__(self, "_inner").commit()


class FaultyUnitOfWorkFactory:
    def __init__(
        self, inner: MemoryDataUnitOfWorkFactory, *, fail_next_commit: bool
    ) -> None:
        self._inner = inner
        self._fail_next_commit = fail_next_commit

    def __call__(self) -> FaultyUnitOfWork:
        fail = self._fail_next_commit
        self._fail_next_commit = False
        return FaultyUnitOfWork(self._inner(), fail_next_commit=fail)


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


def _events(database: MemoryDatabase) -> list[OutboxEvent]:
    events = [
        delivery.event
        for (_tenant_id, _event_id), delivery in database.state.outbox_by_id.items()
    ]
    return sorted(events, key=lambda event: (event.sequence, event.event_id))


def test_worker_publishes_full_lifecycle_events_in_order(
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
            event_publisher=TaskEventPublisher(clock=fixed_clock),
        )
        graph = _graph(
            checkpoints=checkpoints,
            runtime=FakeAgentRuntime(clock=fixed_clock),
            clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        worker = RuntimeWorker(
            worker_id="worker-events",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_events_12345678",
        )

        result = await worker.run_once()
        assert result.graph_outcome is not None
        assert result.graph_outcome.state.status is GraphStatus.COMPLETED

        events = _events(database)
        assert [event.sequence for event in events] == [1, 2, 3]
        assert [event.event_type for event in events] == [
            "task.created.v1",
            "task.status.changed.v1",
            "task.completed.v1",
        ]
        assert all(event.aggregate_type == "task" for event in events)
        assert all(
            event.aggregate_id == command.task_id for event in events
        )
        assert all(event.tenant_id == command.tenant_id for event in events)
        assert events[0].payload == {
            "status": "RECEIVED",
            "task_ref": f"task://{command.task_id}",
        }
        assert events[1].payload == {
            "from": "RECEIVED",
            "to": "RUNNING",
            "reason_code": "agent_attempt",
        }
        assert events[2].payload == {
            "result_ref": events[2].payload["result_ref"]
        }
        assert "runtime-result://" in events[2].payload["result_ref"]

    asyncio.run(scenario())


def test_failed_run_publishes_failed_event(
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
            event_publisher=TaskEventPublisher(clock=fixed_clock),
        )
        graph = _graph(
            checkpoints=checkpoints,
            runtime=FakeAgentRuntime(
                clock=fixed_clock,
                default=FakeScenario(
                    outcome=FakeOutcome.INTERNAL_FAILURE,
                ),
            ),
            clock=fixed_clock,
            context_policy=context_policy,
            agent_profile=agent_profile,
            provider_selection=provider_selection,
            runtime_budget=runtime_budget,
        )
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        worker = RuntimeWorker(
            worker_id="worker-events",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_events_12345678",
        )

        result = await worker.run_once()
        assert result.graph_outcome is not None
        assert result.graph_outcome.state.status is GraphStatus.FAILED

        events = _events(database)
        assert [event.event_type for event in events] == [
            "task.created.v1",
            "task.status.changed.v1",
            "task.failed.v1",
        ]
        assert events[2].payload["error_code"]
        assert events[2].payload["retryable"] is False
        assert [event.sequence for event in events] == [1, 2, 3]

    asyncio.run(scenario())


def test_user_input_interrupt_publishes_input_required(
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
            event_publisher=TaskEventPublisher(clock=fixed_clock),
        )
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_events_12345678",
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
        restored = await checkpoints.save(
            running, expected_sequence=0, lease=lease
        )
        waiting = restored.transition(
            GraphStatus.WAITING_USER,
            node=GraphNode.INTERRUPT,
            pending_reason="user_input:req_12345678",
        )
        await checkpoints.save(
            waiting, expected_sequence=1, lease=lease
        )

        events = _events(database)
        assert [event.event_type for event in events] == [
            "task.created.v1",
            "task.input.required.v1",
        ]
        assert events[1].payload == {
            "request_id": "req_12345678",
            "prompt_ref": (
                f"task://{command.task_id}/user-input/req_12345678"
            ),
            "missing_fields": ("user_input",),
        }
        assert [event.sequence for event in events] == [1, 2]

    asyncio.run(scenario())


def test_fault_before_commit_rolls_outbox_events_back(
    command_factory: Callable[..., TaskCommand],
    task_factory: Callable[..., Task],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        database = MemoryDatabase()
        database.seed_task(task_factory())
        inner = MemoryDataUnitOfWorkFactory(database)
        unit_of_work = FaultyUnitOfWorkFactory(
            inner, fail_next_commit=True
        )
        leases = PersistenceLeaseAdapter(inner, clock=fixed_clock)
        checkpoints = PersistenceCheckpointAdapter(
            unit_of_work,
            clock=fixed_clock,
            event_publisher=TaskEventPublisher(clock=fixed_clock),
        )
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_events_12345678",
        )
        state = GraphState(
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

        with pytest.raises(GraphError) as caught:
            await checkpoints.save(state, expected_sequence=0, lease=lease)
        assert caught.value.code is GraphErrorCode.CHECKPOINT_UNAVAILABLE

        assert _events(database) == []
        async with inner() as unit_of_work:
            assert (
                await unit_of_work.outbox.unpublished(
                    command.tenant_id,
                    now=fixed_clock(),
                    limit=10,
                )
                == ()
            )
            assert await unit_of_work.checkpoints.latest(
                command.tenant_id,
                command.task_id,
                task_factory().thread_id,
            ) is None

    asyncio.run(scenario())


def test_replayed_checkpoint_publishes_no_duplicate_event(
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
            event_publisher=TaskEventPublisher(clock=fixed_clock),
        )
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_events_12345678",
        )
        state = GraphState(
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

        first = await checkpoints.save(
            state, expected_sequence=0, lease=lease
        )
        replay = await checkpoints.save(
            state, expected_sequence=0, lease=lease
        )

        assert replay == first
        events = _events(database)
        assert len(events) == 1
        assert events[0].event_type == "task.created.v1"
        assert events[0].sequence == 1

    asyncio.run(scenario())


def test_events_are_secret_free_and_tenant_scoped(
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
            event_publisher=TaskEventPublisher(clock=fixed_clock),
        )
        lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_events_12345678",
        )
        state = GraphState(
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
        await checkpoints.save(state, expected_sequence=0, lease=lease)

        events = _events(database)
        assert len(events) == 1
        assert events[0].tenant_id == command.tenant_id
        assert events[0].payload == {
            "status": "RECEIVED",
            "task_ref": f"task://{command.task_id}",
        }
        assert "api_key" not in str(events[0].payload).casefold()

    asyncio.run(scenario())
