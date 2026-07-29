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
from flowpilot_domain import TaskCommand, canonical_sha256  # noqa: E402
from flowpilot_persistence import (  # noqa: E402
    CheckpointRecord,
    ExecutionIntent,
    ExecutionOutcome,
    LedgerStatus,
    OutboxEvent,
    PersistenceError,
    PersistenceErrorCode,
    PostgresDataUnitOfWorkFactory,
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
            '{
                "tenant_id":"tenant-a",
                "task_id":"task_12345678",
                "version":1,
                "run_generation":0
            }'::jsonb,
            '2026-07-28T08:00:00Z',
            '2026-07-28T08:00:00Z'
        )
        ON CONFLICT DO NOTHING
        """
    )
    lease_task_id = f"task_lease{suffix}"
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
                {
                    "tenant_id": "tenant-a",
                    "task_id": lease_task_id,
                    "version": 1,
                    "run_generation": 0,
                }
            ),
        },
    )
    await seed.commit()
    await seed.close()

    lease_time = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)
    async with unit_of_work() as data:
        first_fence = await data.leases.acquire(
            "tenant-a",
            lease_task_id,
            "worker-a",
            now=lease_time,
            ttl=timedelta(seconds=30),
        )
        await data.checkpoints.put(
            CheckpointRecord(
                checkpoint_id=f"cp_first{suffix}",
                tenant_id="tenant-a",
                task_id=lease_task_id,
                thread_id=lease_thread_id,
                run_generation=first_fence.run_generation,
                graph_version="graph-v1",
                state={"current_step": "plan"},
                security_context_ref="security-context://tenant-a/adapter",
                security_context_hash="sha256:" + "a" * 64,
                created_at=lease_time,
            ),
            first_fence,
        )
        await data.commit()

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
                    graph_version="graph-v1",
                    state={"current_step": "stale"},
                    security_context_ref="security-context://tenant-a/adapter",
                    security_context_hash="sha256:" + "a" * 64,
                    created_at=recovered_at,
                ),
                first_fence,
            )
        except PersistenceError as exc:
            if exc.code is not PersistenceErrorCode.STALE_FENCE:
                raise
        else:
            raise AssertionError("stale worker checkpoint was accepted")
        await data.checkpoints.put(
            CheckpointRecord(
                checkpoint_id=f"cp_second{suffix}",
                tenant_id="tenant-a",
                task_id=lease_task_id,
                thread_id=lease_thread_id,
                run_generation=second_fence.run_generation,
                graph_version="graph-v1",
                state={"current_step": "resume"},
                security_context_ref="security-context://tenant-a/adapter",
                security_context_hash="sha256:" + "a" * 64,
                created_at=recovered_at,
            ),
            second_fence,
        )
        await data.commit()

    async with unit_of_work() as data:
        latest = await data.checkpoints.latest(
            "tenant-a", lease_thread_id
        )
        if latest is None or latest.checkpoint_id != f"cp_second{suffix}":
            raise AssertionError("checkpoint recovery did not select the new fence")
        await data.commit()

    planned_action = case_instance("planned_action.server_constructed.valid")
    policy_decision = case_instance("policy.single_approval.valid")
    approval = case_instance("approval.sod.valid")
    action_expiry = datetime.fromisoformat(
        planned_action["expires_at"].replace("Z", "+00:00")
    )
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
        action_digest=canonical_sha256(planned_action),
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
        f"generation={latest.run_generation} "
        f"ledger={verified.status.value} attempts={verified.attempt_count}"
    )


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(
            selectors.SelectSelector()
        ),
    )
