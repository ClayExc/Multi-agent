from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from flowpilot_domain import Task
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
