from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flowpilot_domain import Task
from flowpilot_persistence import (
    LeaseFence,
    PersistenceError,
    PersistenceErrorCode,
    PostgresDataUnitOfWorkFactory,
)

NOW = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)


class RecoveryConnection:
    def __init__(self, rows: Sequence[Mapping[str, Any]] = ()) -> None:
        self.rows = rows
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        self.statements.append((statement, parameters))
        return 1

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        return None

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        self.statements.append((statement, parameters))
        return self.rows

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def runnable_mapping(task_projection: Task) -> dict[str, Any]:
    value = task_projection.to_mapping()
    value.update(
        {
            "status": "RUNNABLE",
            "run_generation": 3,
            "active_run_id": None,
            "latest_checkpoint_id": None,
            "result_ref": None,
            "error": None,
            "completed_at": None,
        }
    )
    return Task.from_mapping(value).to_mapping()


def recovery_row(task_projection: Task) -> dict[str, Any]:
    projection = runnable_mapping(task_projection)
    return {
        "tenant_id": projection["tenant_id"],
        "task_id": projection["task_id"],
        "thread_id": projection["thread_id"],
        "status": projection["status"],
        "run_generation": projection["run_generation"],
        "projection": projection,
        "available_at": NOW,
    }


def test_postgres_recovery_reads_latest_outbox_even_after_publish(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        connection = RecoveryConnection((recovery_row(task_projection),))

        async def connection_factory() -> RecoveryConnection:
            return connection

        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            signals = await data.recovery.runnable_signals(
                task_projection.tenant_id,
                now=NOW,
                limit=10,
            )

        assert len(signals) == 1
        assert signals[0].task_id == task_projection.task_id
        assert signals[0].run_generation == 3
        query, parameters = next(
            (statement, values)
            for statement, values in connection.statements
            if "WITH latest_task_event" in statement
        )
        assert "DISTINCT ON (aggregate_id)" in query
        assert "task.status = 'RUNNABLE'" in query
        assert "published_at" not in query
        assert parameters == {
            "tenant_id": task_projection.tenant_id,
            "now": NOW,
            "limit": 10,
        }

    asyncio.run(scenario())


def test_postgres_recovery_rejects_cross_tenant_projection(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        row = recovery_row(task_projection)
        row["tenant_id"] = "tenant-b"
        connection = RecoveryConnection((row,))

        async def connection_factory() -> RecoveryConnection:
            return connection

        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            with pytest.raises(PersistenceError) as caught:
                await data.recovery.runnable_signals(
                    task_projection.tenant_id,
                    now=NOW,
                    limit=10,
                )
            assert caught.value.code is PersistenceErrorCode.DRIVER_PROTOCOL

    asyncio.run(scenario())


def test_postgres_release_revokes_without_deleting_generation_row() -> None:
    async def scenario() -> None:
        connection = RecoveryConnection()

        async def connection_factory() -> RecoveryConnection:
            return connection

        fence = LeaseFence(
            tenant_id="tenant-a",
            task_id="task_release123",
            holder_id="worker-a",
            lease_token="lease_release123",
            run_generation=7,
            acquired_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            await data.leases.release(fence)

        statement = next(
            sql
            for sql, _ in connection.statements
            if "UPDATE flowpilot.task_leases" in sql
        )
        assert "DELETE FROM flowpilot.task_leases" not in statement
        assert "SET lease_token = 'released_' || lease_token" in statement
        assert "expires_at = acquired_at" in statement
        assert "run_generation = %(run_generation)s" in statement

    asyncio.run(scenario())
