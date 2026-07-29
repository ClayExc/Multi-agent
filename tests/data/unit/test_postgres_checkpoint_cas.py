from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flowpilot_persistence import (
    CheckpointRecord,
    LeaseFence,
    PersistenceError,
    PersistenceErrorCode,
    PostgresDataUnitOfWorkFactory,
)

NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)


def candidate(*, state: str = "plan") -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id="cp_atomic123",
        tenant_id="tenant-a",
        task_id="task_atomic123",
        thread_id="thread_atomic123",
        run_generation=1,
        checkpoint_sequence=0,
        graph_version="graph-v1",
        state={"current_step": state},
        security_context_ref="security-context://tenant-a/atomic",
        security_context_hash="sha256:" + "a" * 64,
        created_at=NOW,
    )


def fence() -> LeaseFence:
    return LeaseFence(
        tenant_id="tenant-a",
        task_id="task_atomic123",
        holder_id="worker-a",
        lease_token="lease_atomic123",
        run_generation=1,
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )


def checkpoint_row(
    record: CheckpointRecord,
    *,
    current_sequence: int | None = None,
) -> dict[str, Any]:
    return {
        "checkpoint_id": record.checkpoint_id,
        "tenant_id": record.tenant_id,
        "task_id": record.task_id,
        "thread_id": record.thread_id,
        "run_generation": record.run_generation,
        "checkpoint_sequence": record.checkpoint_sequence,
        "graph_version": record.graph_version,
        "state": dict(record.state),
        "security_context_ref": record.security_context_ref,
        "security_context_hash": record.security_context_hash,
        "created_at": record.created_at,
        "current_sequence": current_sequence,
    }


class CheckpointConnection:
    def __init__(
        self,
        *,
        active_fence: bool = True,
        existing: Mapping[str, Any] | None = None,
        insert_count: int = 1,
        latest: Mapping[str, Any] | None = None,
    ) -> None:
        self.active_fence = active_fence
        self.existing = existing
        self.insert_count = insert_count
        self.latest = latest
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        self.statements.append((statement, parameters))
        if "INSERT INTO flowpilot.checkpoints" in statement:
            return self.insert_count
        return 1

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        if "FOR UPDATE OF lease" in statement:
            return {"run_generation": 1} if self.active_fence else None
        if "AS current_sequence" in statement:
            return self.existing
        if "ORDER BY checkpoint_sequence DESC" in statement:
            return self.latest
        return None

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        self.statements.append((statement, parameters))
        return ()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_postgres_checkpoint_cas_locks_fence_and_increments_sequence() -> None:
    async def scenario() -> None:
        connection = CheckpointConnection()

        async def connection_factory() -> CheckpointConnection:
            return connection

        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            stored = await data.checkpoints.put(
                candidate(),
                fence(),
                expected_sequence=0,
            )

        assert stored.checkpoint_sequence == 1
        sql = "\n".join(statement for statement, _ in connection.statements)
        assert "FOR UPDATE OF lease" in sql
        assert "lease.expires_at > %(observed_at)s" in sql
        assert "max(current.checkpoint_sequence)" in sql
        assert ") = %(expected_sequence)s" in sql

    asyncio.run(scenario())


def test_postgres_checkpoint_cas_fails_before_insert_for_stale_fence() -> None:
    async def scenario() -> None:
        connection = CheckpointConnection(active_fence=False)

        async def connection_factory() -> CheckpointConnection:
            return connection

        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            with pytest.raises(PersistenceError) as caught:
                await data.checkpoints.put(
                    candidate(),
                    fence(),
                    expected_sequence=0,
                )
            assert caught.value.code is PersistenceErrorCode.STALE_FENCE

        assert not any(
            "INSERT INTO flowpilot.checkpoints" in statement
            for statement, _ in connection.statements
        )

    asyncio.run(scenario())


def test_postgres_checkpoint_cas_replays_identical_identity() -> None:
    async def scenario() -> None:
        stored = replace(candidate(), checkpoint_sequence=1)
        connection = CheckpointConnection(
            existing=checkpoint_row(stored, current_sequence=1)
        )

        async def connection_factory() -> CheckpointConnection:
            return connection

        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            replayed = await data.checkpoints.put(
                candidate(),
                fence(),
                expected_sequence=0,
            )
        assert replayed == stored

    asyncio.run(scenario())


def test_postgres_checkpoint_cas_rejects_identity_and_sequence_conflicts() -> None:
    async def scenario() -> None:
        stored = replace(
            candidate(state="other"),
            checkpoint_sequence=1,
        )
        identity_connection = CheckpointConnection(
            existing=checkpoint_row(stored, current_sequence=1)
        )

        async def identity_factory() -> CheckpointConnection:
            return identity_connection

        async with PostgresDataUnitOfWorkFactory(identity_factory)() as data:
            with pytest.raises(PersistenceError) as identity:
                await data.checkpoints.put(
                    candidate(),
                    fence(),
                    expected_sequence=0,
                )
            assert identity.value.code is PersistenceErrorCode.CONFLICT

        cas_connection = CheckpointConnection(insert_count=0)

        async def cas_factory() -> CheckpointConnection:
            return cas_connection

        async with PostgresDataUnitOfWorkFactory(cas_factory)() as data:
            with pytest.raises(PersistenceError) as cas:
                await data.checkpoints.put(
                    candidate(),
                    fence(),
                    expected_sequence=0,
                )
            assert cas.value.code is PersistenceErrorCode.VERSION_CONFLICT

    asyncio.run(scenario())


def test_postgres_latest_binds_tenant_task_thread_and_sequence_order() -> None:
    async def scenario() -> None:
        stored = replace(candidate(), checkpoint_sequence=2)
        connection = CheckpointConnection(latest=checkpoint_row(stored))

        async def connection_factory() -> CheckpointConnection:
            return connection

        async with PostgresDataUnitOfWorkFactory(connection_factory)() as data:
            latest = await data.checkpoints.latest(
                "tenant-a",
                "task_atomic123",
                "thread_atomic123",
            )
        assert latest == stored
        query, parameters = next(
            (statement, values)
            for statement, values in connection.statements
            if "ORDER BY checkpoint_sequence DESC" in statement
        )
        assert "task_id = %(task_id)s" in query
        assert "thread_id = %(thread_id)s" in query
        assert parameters == {
            "tenant_id": "tenant-a",
            "task_id": "task_atomic123",
            "thread_id": "thread_atomic123",
        }

    asyncio.run(scenario())
