from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime

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
from flowpilot_domain import TaskCommand
from flowpilot_graph import (
    GraphError,
    GraphErrorCode,
    GraphNode,
    GraphState,
    GraphStatus,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_worker import (
    InMemoryExecutionQueue,
    RuntimeExecutionAdapter,
    RuntimeWorker,
)
from identity_helpers import MutableSecurityContextValidator


def _request_id(command_id: str, attempt: int) -> str:
    suffix = hashlib.sha256(
        f"{command_id}:{attempt}".encode()
    ).hexdigest()[:16]
    return f"arq_{suffix}"


def test_retryable_failure_resumes_from_checkpoint_with_new_run_generation(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        runtime = FakeAgentRuntime(clock=fixed_clock)
        runtime.script(
            _request_id(command.command_id, 1),
            (FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),),
        )
        graph, _, checkpoints, leases = graph_factory(runtime=runtime)
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)
        first_worker = RuntimeWorker(
            worker_id="worker-a",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_11111111",
        )
        second_worker = RuntimeWorker(
            worker_id="worker-b",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_22222222",
        )

        first = await first_worker.run_once()
        retry_checkpoint = await checkpoints.load(
            command.tenant_id, command.task_id
        )
        second = await second_worker.run_once()
        completed = await checkpoints.load(command.tenant_id, command.task_id)

        assert first.graph_outcome is not None
        assert first.graph_outcome.should_retry is True
        assert retry_checkpoint is not None
        assert retry_checkpoint.status is GraphStatus.RETRY_PENDING
        assert second.graph_outcome is not None
        assert second.graph_outcome.state.status is GraphStatus.COMPLETED
        assert completed is not None
        assert completed.run_generation == 2
        assert completed.run_id == "run_22222222"
        assert completed.attempt_count == 2
        assert len(runtime.calls) == 2
        assert queue.acknowledged_count == 1

    asyncio.run(scenario())


def test_queue_signal_can_be_recovered_after_worker_crash(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        graph, _, _, leases = graph_factory()
        queue = InMemoryExecutionQueue()
        await RuntimeExecutionAdapter(queue).submit(command)

        abandoned = await queue.dequeue("dead-worker")
        assert abandoned is not None
        assert queue.recover_inflight("dead-worker") == 1

        replacement = RuntimeWorker(
            worker_id="replacement-worker",
            queue=queue,
            leases=leases,
            graph=graph,
            security_contexts=MutableSecurityContextValidator(),
            run_id_factory=lambda: "run_33333333",
        )
        result = await replacement.run_once()

        assert result.graph_outcome is not None
        assert result.graph_outcome.state.status is GraphStatus.COMPLETED
        assert queue.acknowledged_count == 1

    asyncio.run(scenario())


def test_expired_old_worker_is_fenced_from_checkpoint_write(
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        leases = InMemoryLeaseStore(clock=fixed_clock)
        checkpoints = InMemoryCheckpointStore(leases=leases)
        old_lease = await leases.acquire(
            "tenant-a", "task_12345678", "run_11111111"
        )
        state = GraphState(
            task_id="task_12345678",
            tenant_id="tenant-a",
            command_id="cmd_12345678",
            command_digest="sha256:" + "a" * 64,
            run_id=old_lease.run_id,
            run_generation=old_lease.run_generation,
            graph_version="graph-v1",
            status=GraphStatus.QUEUED,
            node=GraphNode.START,
            security_context_ref="security-context://tenant-a/12345678",
            security_context_hash="sha256:" + "b" * 64,
            purpose="it_support",
        )
        saved = await checkpoints.save(
            state,
            expected_sequence=0,
            lease=old_lease,
        )
        leases.force_expire("tenant-a", "task_12345678")
        new_lease = await leases.acquire(
            "tenant-a", "task_12345678", "run_22222222"
        )
        assert new_lease.run_generation == 2

        with pytest.raises(GraphError) as captured:
            await checkpoints.save(
                saved,
                expected_sequence=saved.checkpoint_sequence,
                lease=old_lease,
            )

        assert captured.value.code is GraphErrorCode.LEASE_LOST

    asyncio.run(scenario())


def test_graph_version_change_requires_explicit_checkpoint_migration(
    command_factory: Callable[..., TaskCommand],
    graph_factory: Callable[..., tuple],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        graph_v1, runtime, checkpoints, leases = graph_factory(
            graph_version="graph-v1"
        )
        lease_v1 = await leases.acquire(
            command.tenant_id, command.task_id, "run_11111111"
        )
        await graph_v1.execute(
            command,
            execution_ref="execution://tenant-a/cmd_12345678",
            lease=lease_v1,
        )
        await leases.release(lease_v1)

        config_v2 = RuntimeGraphConfig(
            graph_version="graph-v2",
            context_policy=context_policy,
            agent=agent_profile,
            provider=provider_selection,
            budget=runtime_budget,
        )
        kernel_v2 = RuntimeGraphKernel(
            config=config_v2,
            context_builder=ContextBuilder(clock=fixed_clock),
            runtime=runtime,
            checkpoints=checkpoints,
            clock=fixed_clock,
        )
        graph_v2 = LangGraphRuntime(kernel_v2)
        lease_v2 = await leases.acquire(
            command.tenant_id, command.task_id, "run_22222222"
        )

        with pytest.raises(GraphError) as captured:
            await graph_v2.execute(
                command,
                execution_ref="execution://tenant-a/cmd_12345678",
                lease=lease_v2,
            )

        assert captured.value.code is GraphErrorCode.VERSION_MIGRATION_REQUIRED

    asyncio.run(scenario())


def test_crash_after_runtime_checkpoint_reuses_the_same_attempt(
    command_factory: Callable[..., TaskCommand],
    context_policy: ContextPolicy,
    agent_profile: AgentProfile,
    provider_selection: ProviderSelection,
    runtime_budget: RuntimeBudget,
    fixed_clock: Callable[[], datetime],
) -> None:
    async def scenario() -> None:
        command = command_factory()
        runtime = FakeAgentRuntime(clock=fixed_clock)
        leases = InMemoryLeaseStore(clock=fixed_clock)
        checkpoints = InMemoryCheckpointStore(leases=leases)
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
        abandoned_lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_abandoned_12345678",
        )
        prepared = await kernel.prepare(
            command,
            execution_ref="execution://tenant-a/cmd_12345678",
            lease=abandoned_lease,
        )
        assert prepared.request is not None
        original_request_id = prepared.request.request_id
        await leases.release(abandoned_lease)

        replacement_lease = await leases.acquire(
            command.tenant_id,
            command.task_id,
            "run_replacement_12345678",
        )
        outcome = await LangGraphRuntime(kernel).execute(
            command,
            execution_ref="execution://tenant-a/cmd_12345678",
            lease=replacement_lease,
        )

        assert outcome.state.status is GraphStatus.COMPLETED
        assert outcome.state.attempt_count == 1
        assert outcome.state.run_generation == 2
        assert len(runtime.calls) == 1
        assert runtime.calls[0].request_id == original_request_id

    asyncio.run(scenario())
