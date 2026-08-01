from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import selectors
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[3]
for package in ("domain", "application", "persistence"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from flowpilot_application import CommandIntakeService  # noqa: E402
from flowpilot_application.testing import FakeExecutionPort  # noqa: E402
from flowpilot_domain import PlannedAction, Task, TaskCommand  # noqa: E402
from flowpilot_persistence import (  # noqa: E402
    CheckpointRecord,
    CoordinationRebuilder,
    ExecutionIntent,
    ExecutionOutcome,
    LedgerStatus,
    MemoryRedisClient,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
    PostgresDataUnitOfWorkFactory,
    RedisCoordinationAdapter,
    RetryBasis,
)


class PsycopgConnection:
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


def case_instance(case_id: str) -> dict[str, Any]:
    cases = json.loads(
        (ROOT / "contracts" / "conformance" / "rc2-cases.json").read_text(
            encoding="utf-8"
        )
    )
    return copy.deepcopy(
        next(
            case["instance"]
            for case in cases["cases"]
            if case["case_id"] == case_id
        )
    )


def command_fixture(suffix: str) -> TaskCommand:
    value = case_instance("task_command.create.valid")
    value["command_id"] = f"cmd_{suffix}"
    value["task_id"] = f"task_{suffix}"
    value["idempotency_key"] = (
        "sha256:" + hashlib.sha256(suffix.encode("ascii")).hexdigest()
    )
    value["command_digest"] = "sha256:" + "0" * 64
    unsigned = TaskCommand.from_mapping(value)
    value["command_digest"] = unsigned.recompute_digest()
    return TaskCommand.from_mapping(value)


def runnable_task_projection(
    task_id: str,
    thread_id: str,
    *,
    version: int = 1,
    run_generation: int = 0,
) -> dict[str, Any]:
    value = case_instance("task.completed.valid")
    value.update(
        {
            "task_id": task_id,
            "thread_id": thread_id,
            "status": "RUNNABLE",
            "version": version,
            "run_generation": run_generation,
            "active_run_id": None,
            "latest_checkpoint_id": None,
            "result_ref": None,
            "error": None,
            "completed_at": None,
        }
    )
    return Task.from_mapping(value).to_mapping()


async def main() -> None:
    database_url = os.environ["FLOWPILOT_TEST_DATABASE_URL"]
    suffix = uuid4().hex[:12]

    async def connection_factory() -> PsycopgConnection:
        connection = await psycopg.AsyncConnection.connect(
            database_url,
            row_factory=dict_row,
        )
        return PsycopgConnection(connection)

    unit_of_work = PostgresDataUnitOfWorkFactory(connection_factory)
    execution = FakeExecutionPort()
    service = CommandIntakeService(
        unit_of_work=unit_of_work,
        execution=execution,
    )
    command = command_fixture(suffix)

    first = await service.accept(command)
    replay = await service.accept(command)

    if first.replayed or not replay.replayed:
        raise AssertionError("PostgreSQL command replay disposition is invalid")
    if first.execution_receipt != replay.execution_receipt:
        raise AssertionError("PostgreSQL replay did not return the first receipt")
    if len(execution.calls) != 1:
        raise AssertionError("PostgreSQL inbox dispatched a duplicate command")

    seed = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    await seed.execute("SET ROLE flowpilot_worker")
    await seed.execute(
        "SELECT set_config('flowpilot.tenant_id', 'tenant-a', true)"
    )
    await seed.execute(
        """
        INSERT INTO flowpilot.tasks (
            tenant_id,
            task_id,
            thread_id,
            status,
            version,
            run_generation,
            projection,
            created_at,
            updated_at
        )
        VALUES (
            'tenant-a',
            'task_12345678',
            'thread_12345678',
            'RUNNABLE',
            1,
            0,
            %(projection)s::jsonb,
            '2026-07-28T08:00:00Z',
            '2026-07-28T08:00:00Z'
        )
        ON CONFLICT DO NOTHING
        """,
        {
            "projection": json.dumps(
                runnable_task_projection(
                    "task_12345678",
                    "thread_12345678",
                )
            ),
        },
    )
    lease_task_id = f"task_lease{suffix}"
    decoy_task_id = f"task_decoy{suffix}"
    lease_thread_id = f"thread_lease{suffix}"
    await seed.execute(
        """
        INSERT INTO flowpilot.tasks (
            tenant_id,
            task_id,
            thread_id,
            status,
            version,
            run_generation,
            projection,
            created_at,
            updated_at
        )
        VALUES (
            'tenant-a',
            %(task_id)s,
            %(thread_id)s,
            'RUNNABLE',
            1,
            0,
            %(projection)s::jsonb,
            '2026-07-29T04:00:00Z',
            '2026-07-29T04:00:00Z'
        )
        ON CONFLICT DO NOTHING
        """,
        {
            "task_id": lease_task_id,
            "thread_id": lease_thread_id,
            "projection": json.dumps(
                runnable_task_projection(lease_task_id, lease_thread_id)
            ),
        },
    )
    await seed.execute(
        """
        INSERT INTO flowpilot.tasks (
            tenant_id,
            task_id,
            thread_id,
            status,
            version,
            run_generation,
            projection,
            created_at,
            updated_at
        )
        VALUES (
            'tenant-a',
            %(task_id)s,
            %(thread_id)s,
            'RUNNABLE',
            1,
            0,
            %(projection)s::jsonb,
            '2026-07-29T04:00:00Z',
            '2026-07-29T04:00:00Z'
        )
        ON CONFLICT DO NOTHING
        """,
        {
            "task_id": decoy_task_id,
            "thread_id": lease_thread_id,
            "projection": json.dumps(
                runnable_task_projection(decoy_task_id, lease_thread_id)
            ),
        },
    )
    await seed.commit()
    await seed.close()

    async with unit_of_work() as data:
        restored_task = await data.tasks.get("tenant-a", "task_12345678")
        if (
            restored_task is None
            or restored_task.to_mapping()
            != runnable_task_projection(
                "task_12345678",
                "thread_12345678",
            )
        ):
            raise AssertionError("PostgreSQL Task v1 projection did not round-trip")

    async with unit_of_work() as data:
        if await data.tasks.get("tenant-b", "task_12345678") is not None:
            raise AssertionError("cross-tenant Task query returned a projection")

    recovery_event = OutboxEvent(
        event_id=f"evt_recovery{suffix}",
        tenant_id="tenant-a",
        aggregate_type="task",
        aggregate_id=lease_task_id,
        sequence=1,
        event_type="task.status.changed.v1",
        payload={"from": "RECEIVED", "to": "RUNNABLE"},
        occurred_at=datetime(2026, 7, 29, 3, 59, tzinfo=UTC),
        available_at=datetime(2026, 7, 29, 4, 0, tzinfo=UTC),
    )
    async with unit_of_work() as data:
        await data.outbox.append(recovery_event)
        await data.outbox.mark_published(
            "tenant-a",
            recovery_event.event_id,
            published_at=datetime(2026, 7, 29, 4, 1, tzinfo=UTC),
        )
        await data.commit()

    redis_client = MemoryRedisClient()
    redis_coordination = RedisCoordinationAdapter(redis_client)
    rebuilt = await CoordinationRebuilder(
        unit_of_work,
        redis_coordination,
    ).rebuild(
        ["tenant-a"],
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )
    if rebuilt < 1 or redis_coordination.key(
        "tenant-a",
        lease_task_id,
    ) not in redis_client.values:
        raise AssertionError("published PostgreSQL outbox did not rebuild Redis")

    lease_time = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)
    async with unit_of_work() as data:
        decoy_fence = await data.leases.acquire(
            "tenant-a",
            decoy_task_id,
            "worker-decoy",
            now=lease_time,
            ttl=timedelta(minutes=2),
        )
        decoy_checkpoint = await data.checkpoints.put(
            CheckpointRecord(
                checkpoint_id=f"cp_decoy{suffix}",
                tenant_id="tenant-a",
                task_id=decoy_task_id,
                thread_id=lease_thread_id,
                run_generation=decoy_fence.run_generation,
                checkpoint_sequence=0,
                graph_version="graph-v1",
                state={"current_step": "decoy"},
                security_context_ref="security-context://tenant-a/adapter",
                security_context_hash="sha256:" + "a" * 64,
                created_at=lease_time,
            ),
            decoy_fence,
            expected_sequence=0,
        )
        await data.commit()

    first_candidate = CheckpointRecord(
        checkpoint_id=f"cp_first{suffix}",
        tenant_id="tenant-a",
        task_id=lease_task_id,
        thread_id=lease_thread_id,
        run_generation=1,
        checkpoint_sequence=0,
        graph_version="graph-v1",
        state={"current_step": "plan"},
        security_context_ref="security-context://tenant-a/adapter",
        security_context_hash="sha256:" + "a" * 64,
        created_at=lease_time,
    )
    async with unit_of_work() as data:
        first_fence = await data.leases.acquire(
            "tenant-a",
            lease_task_id,
            "worker-a",
            now=lease_time,
            ttl=timedelta(seconds=30),
        )
        if first_fence.run_generation != first_candidate.run_generation:
            raise AssertionError("first lease generation is not deterministic")
        first_checkpoint = await data.checkpoints.put(
            first_candidate,
            first_fence,
            expected_sequence=0,
        )
        replayed_checkpoint = await data.checkpoints.put(
            first_candidate,
            first_fence,
            expected_sequence=0,
        )
        if (
            first_checkpoint.checkpoint_sequence != 1
            or replayed_checkpoint != first_checkpoint
        ):
            raise AssertionError("first checkpoint or safe replay violated CAS")
        await data.commit()

    async with unit_of_work() as data:
        try:
            await data.checkpoints.put(
                CheckpointRecord(
                    checkpoint_id=f"cp_casconflict{suffix}",
                    tenant_id="tenant-a",
                    task_id=lease_task_id,
                    thread_id=lease_thread_id,
                    run_generation=first_fence.run_generation,
                    checkpoint_sequence=0,
                    graph_version="graph-v1",
                    state={"current_step": "stale-sequence"},
                    security_context_ref="security-context://tenant-a/adapter",
                    security_context_hash="sha256:" + "a" * 64,
                    created_at=lease_time + timedelta(seconds=1),
                ),
                first_fence,
                expected_sequence=0,
            )
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.VERSION_CONFLICT:
                raise
        else:
            raise AssertionError("stale checkpoint sequence was accepted")
        try:
            await data.checkpoints.put(
                CheckpointRecord(
                    checkpoint_id=first_candidate.checkpoint_id,
                    tenant_id=first_candidate.tenant_id,
                    task_id=first_candidate.task_id,
                    thread_id=first_candidate.thread_id,
                    run_generation=first_candidate.run_generation,
                    checkpoint_sequence=0,
                    graph_version=first_candidate.graph_version,
                    state={"current_step": "different-content"},
                    security_context_ref=first_candidate.security_context_ref,
                    security_context_hash=first_candidate.security_context_hash,
                    created_at=first_candidate.created_at,
                ),
                first_fence,
                expected_sequence=0,
            )
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.CONFLICT:
                raise
        else:
            raise AssertionError("checkpoint identity accepted different content")

    recovered_at = lease_time + timedelta(seconds=31)
    async with unit_of_work() as data:
        second_fence = await data.leases.acquire(
            "tenant-a",
            lease_task_id,
            "worker-b",
            now=recovered_at,
            ttl=timedelta(seconds=30),
        )
        try:
            await data.checkpoints.put(
                CheckpointRecord(
                    checkpoint_id=f"cp_stale{suffix}",
                    tenant_id="tenant-a",
                    task_id=lease_task_id,
                    thread_id=lease_thread_id,
                    run_generation=first_fence.run_generation,
                    checkpoint_sequence=1,
                    graph_version="graph-v1",
                    state={"current_step": "stale"},
                    security_context_ref="security-context://tenant-a/adapter",
                    security_context_hash="sha256:" + "a" * 64,
                    created_at=recovered_at,
                ),
                first_fence,
                expected_sequence=1,
            )
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.STALE_FENCE:
                raise
        else:
            raise AssertionError("stale worker checkpoint was accepted")
        second_checkpoint = await data.checkpoints.put(
            CheckpointRecord(
                checkpoint_id=f"cp_second{suffix}",
                tenant_id="tenant-a",
                task_id=lease_task_id,
                thread_id=lease_thread_id,
                run_generation=second_fence.run_generation,
                checkpoint_sequence=1,
                graph_version="graph-v1",
                state={"current_step": "resume"},
                security_context_ref="security-context://tenant-a/adapter",
                security_context_hash="sha256:" + "a" * 64,
                created_at=recovered_at,
            ),
            second_fence,
            expected_sequence=1,
        )
        if second_checkpoint.checkpoint_sequence != 2:
            raise AssertionError("second checkpoint did not advance sequence")
        await data.commit()

    async with unit_of_work() as data:
        await data.leases.release(second_fence)
        await data.commit()

    async with unit_of_work() as data:
        third_fence = await data.leases.acquire(
            "tenant-a",
            lease_task_id,
            "worker-c",
            now=recovered_at + timedelta(seconds=1),
            ttl=timedelta(seconds=30),
        )
        if third_fence.run_generation != second_fence.run_generation + 1:
            raise AssertionError("clean release reset the fencing generation")
        await data.commit()

    async with unit_of_work() as data:
        latest = await data.checkpoints.latest(
            "tenant-a", lease_task_id, lease_thread_id
        )
        if latest is None or latest.checkpoint_id != f"cp_second{suffix}":
            raise AssertionError("checkpoint recovery did not select the new fence")
        if (
            await data.checkpoints.latest(
                "tenant-a",
                lease_task_id,
                f"thread_wrong{suffix}",
            )
            is not None
        ):
            raise AssertionError("checkpoint query accepted a mismatched thread")
        isolated_decoy = await data.checkpoints.latest(
            "tenant-a",
            decoy_task_id,
            lease_thread_id,
        )
        if isolated_decoy != decoy_checkpoint:
            raise AssertionError("same-thread Task checkpoint isolation failed")

    async with unit_of_work() as data:
        if (
            await data.checkpoints.latest(
                "tenant-b",
                lease_task_id,
                lease_thread_id,
            )
            is not None
        ):
            raise AssertionError("cross-tenant checkpoint query returned state")

    planned_action = case_instance("planned_action.server_constructed.valid")
    policy_decision = case_instance("policy.single_approval.valid")
    approval = case_instance("approval.sod.valid")
    action_expiry = datetime.fromisoformat(
        planned_action["expires_at"].replace("Z", "+00:00")
    )
    action_digest = PlannedAction.from_mapping(planned_action).digest()
    policy_decision["action"]["action_digest"] = action_digest
    approval["action_digest"] = action_digest
    ledger_intent = ExecutionIntent(
        tool_execution_id=f"tex_{suffix}",
        request_id=f"treq_{suffix}",
        tenant_id="tenant-a",
        task_id="task_12345678",
        tool_name=planned_action["tool"]["name"],
        idempotency_key=(
            "sha256:"
            + hashlib.sha256(f"ledger:{suffix}".encode("ascii")).hexdigest()
        ),
        action_id=planned_action["action_id"],
        action_digest=action_digest,
        planned_action=planned_action,
        planned_action_expires_at=action_expiry,
        policy_decision_id=policy_decision["decision_id"],
        policy_version=policy_decision["policy_version"],
        policy_decision=policy_decision,
        policy_expires_at=action_expiry,
        tool_schema_hash=planned_action["tool"]["schema_hash"],
        approval_id=approval["approval_id"],
        approval=approval,
        approval_expires_at=action_expiry,
        created_at=datetime(2026, 7, 28, 8, 30, tzinfo=UTC),
    )
    async with unit_of_work() as data:
        await data.ledger.prepare(ledger_intent)
        await data.ledger.mark_running(
            "tenant-a",
            ledger_intent.tool_execution_id,
            now=datetime(2026, 7, 28, 8, 31, tzinfo=UTC),
        )
        await data.ledger.record_outcome(
            "tenant-a",
            ledger_intent.tool_execution_id,
            ExecutionOutcome(
                status=LedgerStatus.UNKNOWN,
                recorded_at=datetime(2026, 7, 28, 8, 32, tzinfo=UTC),
                retryable=False,
                error_code="UPSTREAM_RESULT_UNKNOWN",
                reconciliation={
                    "method": "business_key_lookup",
                    "status": "pending",
                },
            ),
        )
        await data.commit()

    async with unit_of_work() as data:
        pending = await data.ledger.pending_reconciliation(
            "tenant-a", limit=10
        )
        if not any(
            item.intent.tool_execution_id == ledger_intent.tool_execution_id
            for item in pending
        ):
            raise AssertionError("unknown execution was not reconcilable")
        try:
            await data.ledger.mark_running(
                "tenant-a",
                ledger_intent.tool_execution_id,
                now=datetime(2026, 7, 28, 8, 33, tzinfo=UTC),
            )
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.RECONCILIATION_REQUIRED:
                raise
        else:
            raise AssertionError("unknown execution was blindly retried")
        await data.ledger.record_outcome(
            "tenant-a",
            ledger_intent.tool_execution_id,
            ExecutionOutcome(
                status=LedgerStatus.FAILED_RETRYABLE,
                recorded_at=datetime(2026, 7, 28, 8, 34, tzinfo=UTC),
                retryable=True,
                retry_basis=RetryBasis.CONFIRMED_NOT_EXECUTED,
                error_code="UPSTREAM_CONFIRMED_NOT_EXECUTED",
                verification={
                    "method": "business_key_lookup",
                    "matched": False,
                    "observed_ref": "evidence://lookup/adapter",
                },
            ),
        )
        await data.ledger.mark_running(
            "tenant-a",
            ledger_intent.tool_execution_id,
            now=datetime(2026, 7, 28, 8, 35, tzinfo=UTC),
        )
        verified = await data.ledger.record_outcome(
            "tenant-a",
            ledger_intent.tool_execution_id,
            ExecutionOutcome(
                status=LedgerStatus.VERIFIED,
                recorded_at=datetime(2026, 7, 28, 8, 36, tzinfo=UTC),
                retryable=False,
                data={"ticket_id": f"INC-{suffix}"},
                evidence_ref=f"evidence://ticket/{suffix}",
                verification={
                    "method": "business_key_lookup",
                    "matched": True,
                    "observed_ref": f"observation://ticket/{suffix}",
                },
            ),
        )
        if verified.attempt_count != 2:
            raise AssertionError("reconciled execution attempt count is invalid")
        await data.outbox.append(
            OutboxEvent(
                event_id=f"evt_{suffix}",
                tenant_id="tenant-a",
                aggregate_type="tool_execution",
                aggregate_id=ledger_intent.tool_execution_id,
                sequence=1,
                event_type="task.tool_execution.updated.v1",
                payload={
                    "tool_execution_id": ledger_intent.tool_execution_id,
                    "status": "verified",
                },
                occurred_at=datetime(2026, 7, 28, 8, 36, tzinfo=UTC),
                available_at=datetime(2026, 7, 28, 8, 36, tzinfo=UTC),
            )
        )
        await data.commit()

    print(
        "POSTGRES_ADAPTER_OK "
        f"command_id={command.command_id} dispatches={len(execution.calls)} "
        f"checkpoint={latest.checkpoint_id} "
        f"generation={third_fence.run_generation} rebuilt={rebuilt} "
        f"ledger={verified.status.value} attempts={verified.attempt_count}"
    )


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(
            selectors.SelectSelector()
        ),
    )
