"""Reproduce the P2 durable-runtime recovery boundary with real services.

This S7 integration harness uses the production Worker assembly and typed
persistence ports. Direct PostgreSQL and Redis clients are confined to fixture
setup, RLS observation, and disposable coordination-state inspection.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import selectors
import sys
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

import psycopg
from flowpilot_agent_runtime import (
    AgentMode,
    AgentProfile,
    AllowedTool,
    FakeAgentRuntime,
    FakeOutcome,
    FakeScenario,
    OutputSchemaRef,
    ProviderSelection,
    RuntimeBudget,
    ToolOperation,
)
from flowpilot_context import ContextBuilder, ContextPolicy
from flowpilot_domain import DataClassification, Task, TaskCommand
from flowpilot_graph import (
    CheckpointPort,
    GraphError,
    GraphErrorCode,
    GraphExecutionPort,
    GraphRunOutcome,
    GraphState,
    GraphStatus,
    LeaseToken,
    RuntimeGraphConfig,
    RuntimeGraphKernel,
)
from flowpilot_graph.langgraph_runtime import LangGraphRuntime
from flowpilot_persistence import (
    CheckpointRecord,
    CoordinationRebuilder,
    CoordinationSignal,
    DataUnitOfWorkFactory,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
    PostgresDataUnitOfWorkFactory,
    RedisCoordinationAdapter,
)
from flowpilot_worker import (
    DurableGraphFactory,
    InMemoryExecutionQueue,
    PersistenceCheckpointAdapter,
    RuntimeExecutionAdapter,
    TrustedTenantInventory,
    build_durable_runtime,
)
from psycopg.rows import dict_row
from redis.asyncio import Redis

ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = datetime(2026, 7, 28, 8, 30, tzinfo=UTC)
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
GRAPH_VERSION = "graph-v1"
REDIS_NAMESPACE = "flowpilot:wp040:a7:run-signal"


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


class AsyncPostgresConnection(Protocol):
    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int: ...

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None: ...

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...


class PsycopgConnection:
    """Narrow psycopg wrapper consumed by the production persistence port."""

    def __init__(self, connection: psycopg.AsyncConnection[dict[str, Any]]) -> None:
        self._connection = connection

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        cursor = await self._connection.execute(statement, parameters)
        return cursor.rowcount

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        cursor = await self._connection.execute(statement, parameters)
        return await cursor.fetchone()

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        cursor = await self._connection.execute(statement, parameters)
        return await cursor.fetchall()

    async def commit(self) -> None:
        await self._connection.commit()

    async def rollback(self) -> None:
        await self._connection.rollback()

    async def close(self) -> None:
        await self._connection.close()


class RedisProtocolClient:
    """Adapt redis-py to S6's deliberately tiny coordination protocol."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def set(self, name: str, value: str) -> object:
        return await self._client.set(name, value)

    async def delete(self, *names: str) -> int:
        return int(await self._client.delete(*names))

    async def scan_iter(self, match: str) -> AsyncIterator[str | bytes]:
        async for key in self._client.scan_iter(match=match):
            if not isinstance(key, (str, bytes)):
                raise TypeError("Redis scan returned a non-text key")
            yield key


class RecordingGraph:
    """Observe lease identities without changing graph behavior."""

    def __init__(self, delegate: GraphExecutionPort) -> None:
        self._delegate = delegate
        self.leases: list[LeaseToken] = []

    async def execute(
        self,
        command: TaskCommand,
        *,
        execution_ref: str,
        lease: LeaseToken,
    ) -> GraphRunOutcome:
        self.leases.append(lease)
        return await self._delegate.execute(
            command,
            execution_ref=execution_ref,
            lease=lease,
        )


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    redis_loss_observed: bool
    first_rebuilt_signal_count: int
    second_rebuilt_signal_count: int
    terminal_rebuilt_signal_count: int
    first_run_generation: int
    recovered_run_generation: int
    first_checkpoint_sequence: int
    completed_checkpoint_sequence: int
    old_worker_write_attempts: int
    old_worker_successful_writes: int
    stale_cas_successful_writes: int
    terminal_node_reruns: int
    terminal_checkpoint_writes: int
    cross_tenant_successful_reads: int
    redis_keys_after_terminal_rebuild: int
    runtime_calls: int
    control_checkpointers_observed: int


def _case_instance(case_id: str) -> dict[str, Any]:
    document = json.loads(
        (ROOT / "contracts/conformance/rc2-cases.json").read_text(
            encoding="utf-8"
        )
    )
    return copy.deepcopy(
        next(
            case["instance"]
            for case in document["cases"]
            if case["case_id"] == case_id
        )
    )


def _command_fixture(suffix: str) -> TaskCommand:
    value = _case_instance("task_command.create.valid")
    value["command_id"] = f"cmd_durable{suffix}"
    value["task_id"] = f"task_durable{suffix}"
    value["idempotency_key"] = (
        "sha256:" + hashlib.sha256(f"idempotency:{suffix}".encode()).hexdigest()
    )
    value["command_digest"] = "sha256:" + "0" * 64
    unsigned = TaskCommand.from_mapping(value)
    value["command_digest"] = unsigned.recompute_digest()
    return TaskCommand.from_mapping(value)


def _runnable_task(command: TaskCommand, suffix: str) -> Task:
    value = _case_instance("task.completed.valid")
    value.update(
        {
            "task_id": command.task_id,
            "thread_id": f"thread_durable{suffix}",
            "tenant_id": command.tenant_id,
            "status": "RUNNABLE",
            "version": 1,
            "run_generation": 0,
            "active_run_id": None,
            "latest_checkpoint_id": None,
            "purpose": command.security_context.purpose,
            "security_context": command.security_context.to_mapping(),
            "waiting_on": None,
            "result_ref": None,
            "error": None,
            "completed_at": None,
        }
    )
    return Task.from_mapping(value)


def _request_id(command_id: str, attempt: int) -> str:
    suffix = hashlib.sha256(f"{command_id}:{attempt}".encode()).hexdigest()[:16]
    return f"arq_{suffix}"


def _graph_factory(
    runtime: FakeAgentRuntime,
    observed_checkpointers: list[object],
    observed_graphs: list[RecordingGraph],
) -> DurableGraphFactory:
    context_policy = ContextPolicy(
        context_policy_version="ctx-policy-v1",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("test-provider",),
        token_budget=4096,
    )
    agent_profile = AgentProfile(
        id="knowledge-agent",
        version="1.0.0",
        prompt_version="prompt-v1",
        mode=AgentMode.BOUNDED_AGENT_LOOP,
        output_schema=OutputSchemaRef(
            id="schema://knowledge-answer/v1",
            hash="sha256:" + "a" * 64,
        ),
        allowed_tools=(
            AllowedTool(
                name="knowledge.search.v1",
                schema_hash="sha256:" + "b" * 64,
                operation=ToolOperation.READ,
            ),
        ),
        maximum_handoffs=1,
    )
    provider = ProviderSelection(
        provider="test-provider",
        model="deterministic-fake",
        data_policy_id="data-policy-v1",
        routing_reason_code="TEST_CONFORMANCE",
    )
    budget = RuntimeBudget(
        maximum_turns=4,
        maximum_tool_calls=2,
        maximum_input_tokens=4096,
        maximum_output_tokens=1024,
        maximum_total_tokens=5120,
        maximum_cost_microunits=1000,
        timeout_ms=30_000,
    )

    def factory(
        *,
        checkpoints: CheckpointPort,
        control_checkpointer: object,
    ) -> GraphExecutionPort:
        observed_checkpointers.append(control_checkpointer)
        kernel = RuntimeGraphKernel(
            config=RuntimeGraphConfig(
                graph_version=GRAPH_VERSION,
                context_policy=context_policy,
                agent=agent_profile,
                provider=provider,
                budget=budget,
            ),
            context_builder=ContextBuilder(clock=lambda: FIXED_NOW),
            runtime=runtime,
            checkpoints=checkpoints,
            clock=lambda: FIXED_NOW,
        )
        graph = RecordingGraph(LangGraphRuntime(kernel))
        observed_graphs.append(graph)
        return graph

    return factory


async def _seed_task_and_outbox(
    database_url: str,
    unit_of_work: PostgresDataUnitOfWorkFactory,
    task: Task,
) -> None:
    connection = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        await connection.execute("SET ROLE flowpilot_worker")
        await connection.execute(
            "SELECT set_config('flowpilot.tenant_id', %(tenant_id)s, true)",
            {"tenant_id": task.tenant_id},
        )
        await connection.execute(
            """
            INSERT INTO flowpilot.tasks (
                tenant_id, task_id, thread_id, status, version,
                run_generation, projection, created_at, updated_at
            )
            VALUES (
                %(tenant_id)s, %(task_id)s, %(thread_id)s, 'RUNNABLE', 1,
                0, %(projection)s::jsonb, %(created_at)s, %(updated_at)s
            )
            """,
            {
                "tenant_id": task.tenant_id,
                "task_id": task.task_id,
                "thread_id": task.thread_id,
                "projection": json.dumps(task.to_mapping(), sort_keys=True),
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
        )
        await connection.commit()
    finally:
        await connection.close()

    event = OutboxEvent(
        event_id=f"evt_durable{task.task_id.removeprefix('task_durable')}",
        tenant_id=task.tenant_id,
        aggregate_type="task",
        aggregate_id=task.task_id,
        sequence=1,
        event_type="task.status.changed.v1",
        payload={"from": "RECEIVED", "to": "RUNNABLE"},
        occurred_at=FIXED_NOW,
        available_at=FIXED_NOW,
    )
    async with unit_of_work() as data:
        await data.outbox.append(event)
        await data.commit()


async def _mark_task_completed(
    database_url: str,
    task: Task,
    completed_state: GraphState,
    latest_checkpoint_id: str,
) -> None:
    value = task.to_mapping()
    value.update(
        {
            "status": "COMPLETED",
            "version": 2,
            "run_generation": completed_state.run_generation,
            "active_run_id": None,
            "latest_checkpoint_id": latest_checkpoint_id,
            "waiting_on": None,
            "result_ref": completed_state.result_ref,
            "error": None,
            "updated_at": FIXED_NOW,
            "completed_at": FIXED_NOW,
        }
    )
    completed_task = Task.from_mapping(value)
    connection = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        await connection.execute("SET ROLE flowpilot_worker")
        await connection.execute(
            "SELECT set_config('flowpilot.tenant_id', %(tenant_id)s, true)",
            {"tenant_id": task.tenant_id},
        )
        cursor = await connection.execute(
            """
            UPDATE flowpilot.tasks
            SET status = 'COMPLETED',
                version = %(version)s,
                run_generation = %(run_generation)s,
                projection = %(projection)s::jsonb,
                updated_at = %(updated_at)s
            WHERE tenant_id = %(tenant_id)s AND task_id = %(task_id)s
            """,
            {
                "version": completed_task.version,
                "run_generation": completed_task.run_generation,
                "projection": json.dumps(
                    completed_task.to_mapping(), sort_keys=True
                ),
                "updated_at": completed_task.updated_at,
                "tenant_id": completed_task.tenant_id,
                "task_id": completed_task.task_id,
            },
        )
        if cursor.rowcount != 1:
            raise AssertionError("completed Task projection was not updated")
        await connection.commit()
    finally:
        await connection.close()


async def _rls_cross_tenant_reads(database_url: str, task: Task) -> int:
    connection = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        await connection.execute("SET ROLE flowpilot_worker")
        await connection.execute(
            "SELECT set_config('flowpilot.tenant_id', %(tenant_id)s, true)",
            {"tenant_id": TENANT_B},
        )
        task_cursor = await connection.execute(
            "SELECT count(*) AS count FROM flowpilot.tasks WHERE task_id = %(task_id)s",
            {"task_id": task.task_id},
        )
        checkpoint_cursor = await connection.execute(
            """
            SELECT count(*) AS count
            FROM flowpilot.checkpoints
            WHERE task_id = %(task_id)s
            """,
            {"task_id": task.task_id},
        )
        task_row = await task_cursor.fetchone()
        checkpoint_row = await checkpoint_cursor.fetchone()
        assert task_row is not None
        assert checkpoint_row is not None
        return int(task_row["count"]) + int(checkpoint_row["count"])
    finally:
        await connection.rollback()
        await connection.close()


async def _run(database_url: str, redis_url: str) -> RecoveryResult:
    suffix = uuid4().hex[:12]
    command = _command_fixture(suffix)
    task = _runnable_task(command, suffix)

    async def connection_factory() -> AsyncPostgresConnection:
        connection = await psycopg.AsyncConnection.connect(
            database_url,
            row_factory=dict_row,
        )
        await connection.execute("SET ROLE flowpilot_worker")
        return PsycopgConnection(connection)

    unit_of_work = PostgresDataUnitOfWorkFactory(connection_factory)
    unit_of_work_port = cast(DataUnitOfWorkFactory, unit_of_work)
    await _seed_task_and_outbox(database_url, unit_of_work, task)

    raw_redis: Redis = Redis.from_url(redis_url, decode_responses=False)
    redis_client = RedisProtocolClient(raw_redis)
    coordination = RedisCoordinationAdapter(
        redis_client,
        namespace=REDIS_NAMESPACE,
    )
    await raw_redis.flushdb()
    await coordination.signal(
        CoordinationSignal(
            tenant_id=TENANT_B,
            task_id=f"task_stale{suffix}",
            run_generation=99,
            available_at=FIXED_NOW,
        )
    )
    await coordination.clear()
    redis_loss_observed = int(await raw_redis.dbsize()) == 0
    if not redis_loss_observed:
        raise AssertionError("Redis loss was not observed before recovery")

    runtime_port = FakeAgentRuntime(clock=lambda: FIXED_NOW)
    runtime_port.script(
        _request_id(command.command_id, 1),
        (FakeScenario(outcome=FakeOutcome.PROVIDER_UNAVAILABLE),),
    )
    observed_checkpointers: list[object] = []
    observed_graphs: list[RecordingGraph] = []
    graph_factory = _graph_factory(
        runtime_port,
        observed_checkpointers,
        observed_graphs,
    )
    rebuilder = CoordinationRebuilder(unit_of_work_port, coordination)
    tenants = TrustedTenantInventory((TENANT_A, TENANT_B))
    queue = InMemoryExecutionQueue()
    await RuntimeExecutionAdapter(queue).submit(command)

    first_runtime = build_durable_runtime(
        worker_id=f"worker_before_restart_{suffix}",
        queue=queue,
        unit_of_work=unit_of_work_port,
        coordination_rebuilder=rebuilder,
        tenants=tenants,
        graph_factory=graph_factory,
        control_checkpointer=object(),
        clock=lambda: FIXED_NOW,
        run_id_factory=lambda: f"run_before_restart_{suffix}",
    )
    first = await first_runtime.run_once()
    if first.graph_outcome is None or not first.graph_outcome.should_retry:
        raise AssertionError("first Worker did not stop at a durable retry point")
    first_state = first.graph_outcome.state
    first_lease = observed_graphs[0].leases[0]
    if first_lease.run_generation != 1:
        raise AssertionError("first Worker generation is not deterministic")
    first_keys = [
        key
        async for key in raw_redis.scan_iter(match=f"{REDIS_NAMESPACE}:*")
    ]
    if first_runtime.rebuilt_signal_count != 1 or len(first_keys) != 1:
        raise AssertionError("trusted PostgreSQL facts did not rebuild Redis")

    await raw_redis.flushdb()
    if int(await raw_redis.dbsize()) != 0:
        raise AssertionError("Redis was not empty at the restart boundary")

    second_runtime = build_durable_runtime(
        worker_id=f"worker_after_restart_{suffix}",
        queue=queue,
        unit_of_work=unit_of_work_port,
        coordination_rebuilder=rebuilder,
        tenants=tenants,
        graph_factory=graph_factory,
        control_checkpointer=object(),
        clock=lambda: FIXED_NOW,
        run_id_factory=lambda: f"run_after_restart_{suffix}",
    )
    second = await second_runtime.run_once()
    if second.graph_outcome is None:
        raise AssertionError("new Worker did not resume the queued execution")
    completed_state = second.graph_outcome.state
    second_lease = observed_graphs[1].leases[0]
    if (
        completed_state.status is not GraphStatus.COMPLETED
        or second_lease.run_generation != 2
        or completed_state.run_generation != 2
        or completed_state.checkpoint_sequence <= first_state.checkpoint_sequence
    ):
        raise AssertionError("new Worker did not resume with a new fenced generation")

    checkpoints = PersistenceCheckpointAdapter(
        unit_of_work_port,
        clock=lambda: FIXED_NOW,
    )
    restored = await checkpoints.load(task.tenant_id, task.task_id)
    if restored != completed_state:
        raise AssertionError(
            "tenant + task + thread latest checkpoint was not restored"
        )

    old_worker_write_attempts = 1
    old_worker_successful_writes = 0
    try:
        await checkpoints.save(
            first_state,
            expected_sequence=first_state.checkpoint_sequence,
            lease=first_lease,
        )
    except GraphError as exc:
        if exc.code is not GraphErrorCode.LEASE_LOST:
            raise
    else:
        old_worker_successful_writes += 1

    async with unit_of_work() as data:
        latest_record = await data.checkpoints.latest(
            task.tenant_id,
            task.task_id,
            task.thread_id,
        )
    if latest_record is None:
        raise AssertionError("completed checkpoint record is missing")

    stale_cas_successful_writes = 0
    async with unit_of_work() as data:
        cas_fence = await data.leases.acquire(
            task.tenant_id,
            task.task_id,
            f"worker_cas_{suffix}",
            now=FIXED_NOW,
            ttl=timedelta(minutes=1),
        )
        try:
            await data.checkpoints.put(
                CheckpointRecord(
                    checkpoint_id=f"checkpoint://{task.task_id}/stale-cas/{suffix}",
                    tenant_id=task.tenant_id,
                    task_id=task.task_id,
                    thread_id=task.thread_id,
                    run_generation=cas_fence.run_generation,
                    checkpoint_sequence=0,
                    graph_version=GRAPH_VERSION,
                    state=completed_state.to_checkpoint(),
                    security_context_ref=completed_state.security_context_ref,
                    security_context_hash=completed_state.security_context_hash,
                    created_at=FIXED_NOW,
                ),
                cas_fence,
                expected_sequence=0,
            )
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.VERSION_CONFLICT:
                raise
        else:
            stale_cas_successful_writes += 1
        await data.leases.release(cas_fence)
        await data.commit()

    await _mark_task_completed(
        database_url,
        task,
        completed_state,
        latest_record.checkpoint_id,
    )
    await raw_redis.flushdb()

    duplicate_queue = InMemoryExecutionQueue()
    await RuntimeExecutionAdapter(duplicate_queue).submit(command)
    calls_before_terminal_replay = len(runtime_port.calls)
    sequence_before_terminal_replay = completed_state.checkpoint_sequence
    terminal_runtime = build_durable_runtime(
        worker_id=f"worker_terminal_replay_{suffix}",
        queue=duplicate_queue,
        unit_of_work=unit_of_work_port,
        coordination_rebuilder=rebuilder,
        tenants=tenants,
        graph_factory=graph_factory,
        control_checkpointer=object(),
        clock=lambda: FIXED_NOW,
        run_id_factory=lambda: f"run_terminal_replay_{suffix}",
    )
    replay = await terminal_runtime.run_once()
    after_replay = await checkpoints.load(task.tenant_id, task.task_id)
    if (
        replay.graph_outcome is None
        or replay.graph_outcome.state.status is not GraphStatus.COMPLETED
        or after_replay is None
    ):
        raise AssertionError("terminal replay did not remain completed")

    cross_tenant_reads = await _rls_cross_tenant_reads(database_url, task)
    async with unit_of_work() as data:
        if await data.tasks.get(TENANT_B, task.task_id) is not None:
            cross_tenant_reads += 1
        if (
            await data.checkpoints.latest(TENANT_B, task.task_id, task.thread_id)
            is not None
        ):
            cross_tenant_reads += 1

    terminal_node_reruns = len(runtime_port.calls) - calls_before_terminal_replay
    terminal_checkpoint_writes = (
        after_replay.checkpoint_sequence - sequence_before_terminal_replay
    )
    redis_keys_after_terminal = int(await raw_redis.dbsize())
    await raw_redis.aclose()

    second_rebuilt = second_runtime.rebuilt_signal_count
    terminal_rebuilt = terminal_runtime.rebuilt_signal_count
    if second_rebuilt is None or terminal_rebuilt is None:
        raise AssertionError("durable runtime did not record recovery counts")
    result = RecoveryResult(
        redis_loss_observed=redis_loss_observed,
        first_rebuilt_signal_count=first_runtime.rebuilt_signal_count,
        second_rebuilt_signal_count=second_rebuilt,
        terminal_rebuilt_signal_count=terminal_rebuilt,
        first_run_generation=first_lease.run_generation,
        recovered_run_generation=second_lease.run_generation,
        first_checkpoint_sequence=first_state.checkpoint_sequence,
        completed_checkpoint_sequence=completed_state.checkpoint_sequence,
        old_worker_write_attempts=old_worker_write_attempts,
        old_worker_successful_writes=old_worker_successful_writes,
        stale_cas_successful_writes=stale_cas_successful_writes,
        terminal_node_reruns=terminal_node_reruns,
        terminal_checkpoint_writes=terminal_checkpoint_writes,
        cross_tenant_successful_reads=cross_tenant_reads,
        redis_keys_after_terminal_rebuild=redis_keys_after_terminal,
        runtime_calls=len(runtime_port.calls),
        control_checkpointers_observed=len(observed_checkpointers),
    )
    assert_recovery_result(result)
    return result


def assert_recovery_result(result: RecoveryResult) -> None:
    expected_zero = {
        "terminal_rebuilt_signal_count": result.terminal_rebuilt_signal_count,
        "old_worker_successful_writes": result.old_worker_successful_writes,
        "stale_cas_successful_writes": result.stale_cas_successful_writes,
        "terminal_node_reruns": result.terminal_node_reruns,
        "terminal_checkpoint_writes": result.terminal_checkpoint_writes,
        "cross_tenant_successful_reads": result.cross_tenant_successful_reads,
        "redis_keys_after_terminal_rebuild": (
            result.redis_keys_after_terminal_rebuild
        ),
    }
    failures = [name for name, value in expected_zero.items() if value != 0]
    if failures:
        raise AssertionError(f"durable recovery failed closed checks: {failures}")
    if (
        not result.redis_loss_observed
        or result.first_rebuilt_signal_count != 1
        or result.second_rebuilt_signal_count != 1
        or result.first_run_generation != 1
        or result.recovered_run_generation != 2
        or result.completed_checkpoint_sequence
        <= result.first_checkpoint_sequence
        or result.old_worker_write_attempts != 1
        or result.runtime_calls != 2
        or result.control_checkpointers_observed != 3
    ):
        raise AssertionError("durable recovery positive invariants did not hold")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify P2 durable recovery with real PostgreSQL and Redis",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("FLOWPILOT_TEST_DATABASE_URL"),
    )
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("FLOWPILOT_TEST_REDIS_URL"),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url or not args.redis_url:
        raise SystemExit(
            "FLOWPILOT_TEST_DATABASE_URL and FLOWPILOT_TEST_REDIS_URL are required"
        )
    loop_factory: Callable[[], asyncio.AbstractEventLoop] | None = None
    if sys.platform == "win32":
        loop_factory = _selector_loop_factory
    result = asyncio.run(
        _run(args.database_url, args.redis_url),
        loop_factory=loop_factory,
    )
    document = asdict(result)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        "DURABLE_RECOVERY_OK "
        f"generation={result.first_run_generation}->{result.recovered_run_generation} "
        f"checkpoint={result.first_checkpoint_sequence}"
        f"->{result.completed_checkpoint_sequence} "
        f"old_worker_writes={result.old_worker_successful_writes} "
        f"terminal_reruns={result.terminal_node_reruns} "
        f"cross_tenant_reads={result.cross_tenant_successful_reads}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
