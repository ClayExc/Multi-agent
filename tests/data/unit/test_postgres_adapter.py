from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
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
