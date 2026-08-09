from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import pytest
from flowpilot_application import TaskInitializationDisposition
from flowpilot_domain import Task, TaskStatus
from flowpilot_persistence import (
    PersistenceError,
    PersistenceErrorCode,
    PostgresDataUnitOfWorkFactory,
)


class ScriptedConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Mapping[str, object] | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

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
        if "SELECT version" in statement:
            return {"version": 7}
        return None

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        self.statements.append((statement, parameters))
        return ()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


class TaskProjectionConnection(ScriptedConnection):
    def __init__(self, row: Mapping[str, Any] | None) -> None:
        super().__init__()
        self.row = row

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any] | None:
        self.statements.append((statement, parameters))
        if "SELECT tenant_id, task_id, projection" in statement:
            return self.row
        return None


class TaskInitializationConnection(ScriptedConnection):
    def __init__(self, affected: int) -> None:
        super().__init__()
        self.affected = affected

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> int:
        self.statements.append((statement, parameters))
        if "INSERT INTO flowpilot.tasks" in statement:
            return self.affected
        return 1


def _initial_task(task: Task) -> Task:
    return replace(
        task,
        task_id="task_initialize1",
        thread_id="thread_initialize1",
        status=TaskStatus.RECEIVED,
        version=0,
        run_generation=0,
        waiting_on=None,
        result_ref=None,
        error=None,
        completed_at=None,
        active_run_id=None,
        latest_checkpoint_id=None,
        domain=None,
        intent=None,
        risk_level=None,
        updated_at=task.created_at,
    )


def test_postgres_uow_binds_one_tenant_and_commits_once() -> None:
    async def scenario() -> None:
        connection = ScriptedConnection()

        async def connection_factory() -> ScriptedConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.get_version(
                    "tenant-a", "task_12345678"
                )
                == 7
            )
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.tasks.get_version(
                    "tenant-b", "task_12345678"
                )
            assert caught.value.code is PersistenceErrorCode.TENANT_MISMATCH
            await unit_of_work.commit()

        set_context = [
            statement
            for statement, _ in connection.statements
            if "set_config('flowpilot.tenant_id'" in statement
        ]
        assert len(set_context) == 1
        assert connection.commits == 1
        assert connection.rollbacks == 0
        assert connection.closes == 1

    asyncio.run(scenario())


def test_postgres_uow_rolls_back_when_not_committed() -> None:
    async def scenario() -> None:
        connection = ScriptedConnection()

        async def connection_factory() -> ScriptedConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            await unit_of_work.tasks.get_version(
                "tenant-a", "task_12345678"
            )

        assert connection.commits == 0
        assert connection.rollbacks == 1
        assert connection.closes == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("affected", "expected"),
    [
        (1, TaskInitializationDisposition.INITIALIZED),
        (0, TaskInitializationDisposition.CONFLICT),
    ],
)
def test_postgres_task_initialize_is_insert_only(
    task_projection: Task,
    affected: int,
    expected: TaskInitializationDisposition,
) -> None:
    async def scenario() -> None:
        task = _initial_task(task_projection)
        connection = TaskInitializationConnection(affected)

        async def connection_factory() -> TaskInitializationConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.initialize(task.tenant_id, task)
                is expected
            )

        inserts = [
            parameters
            for statement, parameters in connection.statements
            if "INSERT INTO flowpilot.tasks" in statement
        ]
        assert len(inserts) == 1
        assert inserts[0] is not None
        assert inserts[0]["tenant_id"] == task.tenant_id
        assert inserts[0]["task_id"] == task.task_id
        assert inserts[0]["status"] == TaskStatus.RECEIVED.value
        assert inserts[0]["version"] == 0
        assert inserts[0]["run_generation"] == 0

    asyncio.run(scenario())


def test_postgres_task_initialize_rejects_tenant_mismatch_without_insert(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        task = _initial_task(task_projection)
        connection = TaskInitializationConnection(1)

        async def connection_factory() -> TaskInitializationConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.initialize("tenant-b", task)
                is TaskInitializationDisposition.CONFLICT
            )

        assert not any(
            "INSERT INTO flowpilot.tasks" in statement
            for statement, _ in connection.statements
        )

    asyncio.run(scenario())


def test_postgres_task_initialize_rejects_non_initial_projection(
    task_projection: Task,
) -> None:
    async def scenario() -> None:
        connection = TaskInitializationConnection(1)

        async def connection_factory() -> TaskInitializationConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.tasks.initialize(
                    task_projection.tenant_id,
                    task_projection,
                )
            assert caught.value.code is PersistenceErrorCode.DRIVER_PROTOCOL

        assert not any(
            "INSERT INTO flowpilot.tasks" in statement
            for statement, _ in connection.statements
        )

    asyncio.run(scenario())


def test_postgres_task_query_restores_task_v1(task_projection: Task) -> None:
    async def scenario() -> None:
        connection = TaskProjectionConnection(
            {
                "tenant_id": task_projection.tenant_id,
                "task_id": task_projection.task_id,
                "projection": task_projection.to_mapping(),
            }
        )

        async def connection_factory() -> TaskProjectionConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            restored = await unit_of_work.tasks.get(
                task_projection.tenant_id,
                task_projection.task_id,
            )

        assert restored == task_projection

    asyncio.run(scenario())


def test_postgres_task_query_returns_none_for_missing_task() -> None:
    async def scenario() -> None:
        connection = TaskProjectionConnection(None)

        async def connection_factory() -> TaskProjectionConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            assert (
                await unit_of_work.tasks.get("tenant-a", "task_missing000")
                is None
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "row",
    [
        {
            "tenant_id": "tenant-a",
            "task_id": "task_12345678",
            "projection": {"tenant_id": "tenant-a"},
        },
        {
            "tenant_id": "tenant-b",
            "task_id": "task_12345678",
            "projection": None,
        },
    ],
)
def test_postgres_task_query_rejects_malformed_projection(
    row: Mapping[str, Any],
) -> None:
    async def scenario() -> None:
        connection = TaskProjectionConnection(row)

        async def connection_factory() -> TaskProjectionConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.tasks.get("tenant-a", "task_12345678")
            assert caught.value.code is PersistenceErrorCode.DRIVER_PROTOCOL

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("row_tenant", "row_task", "projection_tenant", "projection_task"),
    [
        ("tenant-b", "task_12345678", "tenant-a", "task_12345678"),
        ("tenant-a", "task_other000", "tenant-a", "task_12345678"),
        ("tenant-a", "task_12345678", "tenant-b", "task_12345678"),
        ("tenant-a", "task_12345678", "tenant-a", "task_other000"),
    ],
)
def test_postgres_task_query_rejects_identity_mismatch(
    task_projection: Task,
    row_tenant: str,
    row_task: str,
    projection_tenant: str,
    projection_task: str,
) -> None:
    async def scenario() -> None:
        projection = task_projection.to_mapping()
        projection["tenant_id"] = projection_tenant
        projection["task_id"] = projection_task
        if projection_tenant != task_projection.tenant_id:
            projection["security_context"]["tenant_id"] = projection_tenant
        connection = TaskProjectionConnection(
            {
                "tenant_id": row_tenant,
                "task_id": row_task,
                "projection": projection,
            }
        )

        async def connection_factory() -> TaskProjectionConnection:
            return connection

        factory = PostgresDataUnitOfWorkFactory(connection_factory)
        async with factory() as unit_of_work:
            with pytest.raises(PersistenceError) as caught:
                await unit_of_work.tasks.get("tenant-a", "task_12345678")
            assert caught.value.code is PersistenceErrorCode.DRIVER_PROTOCOL

    asyncio.run(scenario())
